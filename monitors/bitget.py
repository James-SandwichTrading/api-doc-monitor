#!/usr/bin/env python3
"""
Bitget API Documentation Change Monitor with Telegram Notifications

This script monitors Bitget API changelog documentation and tracks changes
by storing section hashes for comparison.

Bitget publishes its changelog as one page per month:
    https://www.bitget.com/docs/uta/changelog/YYYY-MM
    https://www.bitget.com/docs/classic/changelog/YYYY-MM
plus an "Update Preview" page listing upcoming UTA changes:
    https://www.bitget.com/docs/uta/update-preview

Classic accounts have no Update Preview page. Months with no entries have no
page at all (404), which is treated as "nothing to monitor" rather than an error.

The pages are server-rendered, so plain HTTP requests are sufficient (no Selenium).
To keep the monitored range small, only the Update Preview page and the last few
months of changelog pages are tracked.

Automatically sends Telegram notifications when changes are detected.
"""

from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .base_monitor import BaseDocMonitor


class BitgetDocMonitor(BaseDocMonitor):
    BASE_URL = "https://www.bitget.com/docs"

    # Elements ignored when collecting an entry's body. Entry bodies are plain
    # markdown output (p/ul/ol/table/pre); the docs framework's own blocks
    # (spacer and prev/next pagination after the last entry) are divs, so
    # skipping divs keeps navigation churn out of the content hash.
    SKIP_TAGS = ("div", "script", "style", "nav", "footer", "header", "aside")

    def __init__(
        self,
        storage_file: str = "state/bitget_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        monitor_classic: bool = True,
        monitor_uta: bool = True,
        months_to_monitor: int = 3,
        notify_additions: bool = True,
        notify_modifications: bool = True,
        notify_deletions: bool = False,
        notify_no_sections: bool = True,
        notify_many_deletions: bool = True,
        notify_many_deletions_threshold: float = 0.2,
    ):
        """
        Initialize the Bitget documentation monitor.

        Args:
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            monitor_classic: Whether to monitor Classic Account changelog
            monitor_uta: Whether to monitor UTA (Unified Trading Account) changelog
            months_to_monitor: How many monthly changelog pages to monitor,
                counting back from the current month (default: 3)
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """
        super().__init__(
            exchange_name="Bitget",
            storage_file=storage_file,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=telegram_chat_id,
            notify_additions=notify_additions,
            notify_modifications=notify_modifications,
            notify_deletions=notify_deletions,
            notify_no_sections=notify_no_sections,
            notify_many_deletions=notify_many_deletions,
            notify_many_deletions_threshold=notify_many_deletions_threshold,
        )

        # Pages per API type. "changelog" is the base of the monthly pages
        # (YYYY-MM is appended); "update_preview" is the upcoming-changes page.
        self.api_types: Dict[str, Dict[str, str]] = {}
        if monitor_uta:
            self.api_types["uta"] = {
                "update_preview": f"{self.BASE_URL}/uta/update-preview",
                "changelog": f"{self.BASE_URL}/uta/changelog",
            }
        if monitor_classic:
            self.api_types["classic"] = {
                "changelog": f"{self.BASE_URL}/classic/changelog",
            }

        self.months_to_monitor = max(1, int(months_to_monitor))

        # Cache of parsed pages (url -> soup, or None if the fetch failed / 404)
        self._soup_cache: Dict[str, Optional[BeautifulSoup]] = {}

        # Most recent changelog page that actually exists, per API type
        # (used for the Telegram footer links)
        self._latest_changelog_page: Dict[str, str] = {}

    def _months_to_monitor(self) -> List[str]:
        """
        Get the list of months to monitor as YYYY-MM strings, newest first.

        Returns:
            List of month strings, e.g. ["2026-09", "2026-08", "2026-07"]
        """
        today = datetime.now()
        year, month = today.year, today.month
        months = []
        for _ in range(self.months_to_monitor):
            months.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        return months

    def _pages_to_monitor(self) -> List[Tuple[str, str, str]]:
        """
        Build the list of pages to monitor.

        Returns:
            List of (api_type, page_kind, url) tuples, where page_kind is
            "update_preview" or "changelog"
        """
        pages = []
        months = self._months_to_monitor()
        for api_type, urls in self.api_types.items():
            if "update_preview" in urls:
                pages.append((api_type, "update_preview", urls["update_preview"]))
            for month in months:
                pages.append((api_type, "changelog", f"{urls['changelog']}/{month}"))
        return pages

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch and parse a page, caching the result.

        A 404 is expected for months with no changelog entries and is not
        treated as an error.

        Args:
            url: The URL to fetch

        Returns:
            Parsed page, or None if the page does not exist or could not be fetched
        """
        if url in self._soup_cache:
            return self._soup_cache[url]

        soup = None
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 404:
                self.logger.info(f"  No page at {url} (404) - no entries for this month")
            else:
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
        except Exception as e:
            self.logger.error(f"  Error fetching {url}: {e}")

        self._soup_cache[url] = soup
        return soup

    @staticmethod
    def _content_root(soup: BeautifulSoup):
        """Get the main content element of a docs page (falls back to the whole document)."""
        return soup.find("main") or soup

    def _find_entry_headings(self, soup: BeautifulSoup) -> List:
        """
        Find the changelog entry headings on a page.

        Each entry is an h2 with an id (e.g. august-31-2026-spot-auto-borrow-...).

        Args:
            soup: Parsed page

        Returns:
            List of heading elements
        """
        return [
            heading
            for heading in self._content_root(soup).find_all("h2", id=True)
            if heading.get_text(strip=True)
        ]

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover changelog entries from the monitored Bitget documentation pages.

        Returns:
            Dict of url -> section_title
        """
        all_sections = {}
        months = self._months_to_monitor()
        self.logger.info(f"Monitoring changelog months: {', '.join(months)}")

        for api_type, page_kind, url in self._pages_to_monitor():
            kind_label = page_kind.replace("_", " ")
            self.logger.info(f"Fetching {api_type.upper()} {kind_label} from {url}...")

            try:
                soup = self._fetch_page(url)
                if soup is None:
                    continue

                # Pages are iterated newest month first, so the first existing
                # changelog page is the most recent one
                if page_kind == "changelog" and api_type not in self._latest_changelog_page:
                    self._latest_changelog_page[api_type] = url

                headings = self._find_entry_headings(soup)
                for heading in headings:
                    section_id = heading["id"]
                    section_title = heading.get_text(" ", strip=True)
                    full_url = f"{url}#{section_id}"
                    all_sections[full_url] = section_title
                    self.logger.debug(f"  Found section: {section_title} (#{section_id})")

                self.logger.info(
                    f"  Discovered {len(headings)} sections for {api_type} {kind_label}"
                )

            except Exception as e:
                self.logger.error(f"  Error processing {api_type} {kind_label}: {e}")

        return all_sections

    def fetch_section_content(self, section_url: str) -> Tuple[str, str]:
        """
        Fetch a specific section's content and return its content and hash.

        Args:
            section_url: The full section URL (with fragment)

        Returns:
            Tuple of (content, hash)
        """
        if "#" not in section_url:
            return "", ""

        base_url, section_id = section_url.rsplit("#", 1)

        try:
            soup = self._fetch_page(base_url)
            if soup is None:
                return "", ""

            section = self._content_root(soup).find(id=section_id)
            if not section:
                self.logger.warning(f"  Section not found: {section_id}")
                return "", ""

            # Heading text, then everything up to the next entry heading
            content_parts = [section.get_text(" ", strip=True)]

            for sibling in section.find_next_siblings():
                if sibling.name in ("h1", "h2"):
                    break
                if sibling.name in self.SKIP_TAGS:
                    continue

                text = sibling.get_text(separator=" ", strip=True)
                if text:
                    content_parts.append(text)

            content = "\n".join(content_parts)
            content_hash = self.get_page_hash(content)

            return content, content_hash

        except Exception as e:
            self.logger.error(f"  Error fetching section {section_url}: {e}")
            return "", ""

    def get_section_url(self, section_url: str) -> str:
        """
        Get the URL for a specific section.

        Args:
            section_url: The full section URL

        Returns:
            The URL (same as section_url)
        """
        return section_url

    def _changelog_link(self, api_type: str) -> str:
        """Get the most recent existing changelog page URL for an API type."""
        return self._latest_changelog_page.get(api_type) or (
            f"{self.api_types[api_type]['changelog']}/{self._months_to_monitor()[0]}"
        )

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages with documentation links.

        Returns:
            Footer string with documentation links
        """
        lines = []
        for api_type, urls in self.api_types.items():
            label = api_type.upper()
            if "update_preview" in urls:
                lines.append(f"  • [{label} Update Preview]({urls['update_preview']})")
            lines.append(f"  • [{label} Changelog]({self._changelog_link(api_type)})")
        return "\n📚 Documentation:\n" + "\n".join(lines)

    def get_section_label(self, section_id: str) -> str:
        """Get API type label from URL."""
        for api_type in self.api_types:
            if section_id.startswith(f"{self.BASE_URL}/{api_type}/"):
                return api_type.upper()
        return ""

    def print_summary_footer(self):
        """Print footer for summary with documentation URLs."""
        self.logger.info("View documentation at:")
        for api_type, urls in self.api_types.items():
            if "update_preview" in urls:
                self.logger.info(f"  {api_type.upper()} update preview: {urls['update_preview']}")
            self.logger.info(f"  {api_type.upper()} changelog: {self._changelog_link(api_type)}")


def main():
    """Main execution function."""
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Bitget", default_storage_file="state/bitget_docs_state.json"
    )

    # Add Bitget-specific arguments
    parser.add_argument(
        "--classic-only",
        action="store_true",
        help="Monitor only Classic Account changelog",
    )
    parser.add_argument(
        "--uta-only",
        action="store_true",
        help="Monitor only UTA (Unified Trading Account) changelog",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="Number of monthly changelog pages to monitor, counting back from the current month (default: 3)",
    )

    args = parser.parse_args()

    # Determine which APIs to monitor
    monitor_classic = not args.uta_only
    monitor_uta = not args.classic_only

    # Get Telegram credentials
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    (
        notify_additions,
        notify_modifications,
        notify_deletions,
        notify_no_sections,
        notify_many_deletions,
        notify_many_deletions_threshold,
    ) = BaseDocMonitor.get_notification_settings(args)

    # Create monitor instance
    monitor = BitgetDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        monitor_classic=monitor_classic,
        monitor_uta=monitor_uta,
        months_to_monitor=args.months,
        notify_additions=notify_additions,
        notify_modifications=notify_modifications,
        notify_deletions=notify_deletions,
        notify_no_sections=notify_no_sections,
        notify_many_deletions=notify_many_deletions,
        notify_many_deletions_threshold=notify_many_deletions_threshold,
    )

    # Check for changes
    changes = monitor.check_for_changes(save_content=args.save_content)

    # Print summary
    monitor.print_summary(changes)

    # Send Telegram notification if changes detected
    monitor.send_telegram(changes)


if __name__ == "__main__":
    main()
