#!/usr/bin/env python3
"""
Bybit V5 API Documentation Change Monitor with Telegram Notifications

This script monitors two Bybit sources:

1. The V5 API documentation (https://bybit-exchange.github.io/docs/v5/intro)
   - crawls the documentation site and tracks each page's content with
   hash-based detection.
2. Platform announcements from the public API
   (https://api.bybit.com/v5/announcements/index) - each announcement is
   tracked as its own section. Only the newest page(s) of announcements are
   fetched (one page of 50 by default), limited to the current and previous
   year.

Automatically sends Telegram notifications when changes are detected.
"""

from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import time
from typing import Dict, Tuple
from .base_monitor import BaseDocMonitor


class BybitDocMonitor(BaseDocMonitor):
    ANNOUNCEMENTS_API = "https://api.bybit.com/v5/announcements/index"
    ANNOUNCEMENTS_SITE = "https://announcements.bybit.com"
    ANNOUNCEMENTS_LOCALE = "en-US"

    # Announcements requested per page, and the hard ceiling on how many
    # pages max_announcement_pages may ask for
    ANNOUNCEMENTS_PAGE_SIZE = 50
    ANNOUNCEMENTS_MAX_PAGES = 20

    def __init__(
        self,
        storage_file: str = "state/bybit_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        telegram_admin_chat_id: str = None,
        max_pages: int = 1000,
        max_announcement_pages: int = 1,
        monitor_docs: bool = True,
        monitor_announcements: bool = True,
        notify_additions: bool = True,
        notify_modifications: bool = True,
        notify_deletions: bool = False,
        notify_no_sections: bool = True,
        notify_many_deletions: bool = True,
        notify_many_deletions_threshold: float = 0.2,
    ):
        """
        Initialize the Bybit documentation monitor.

        Args:
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            telegram_admin_chat_id: Chat ID that receives the full list when a notification is cut off (optional)
            max_pages: Maximum number of documentation pages to discover
            max_announcement_pages: How many pages of 50 announcements to fetch,
                newest first (default: 1; capped at ANNOUNCEMENTS_MAX_PAGES)
            monitor_docs: Whether to crawl the V5 API documentation
            monitor_announcements: Whether to monitor platform announcements
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """
        super().__init__(
            exchange_name="Bybit",
            storage_file=storage_file,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=telegram_chat_id,
            telegram_admin_chat_id=telegram_admin_chat_id,
            notify_additions=notify_additions,
            notify_modifications=notify_modifications,
            notify_deletions=notify_deletions,
            notify_no_sections=notify_no_sections,
            notify_many_deletions=notify_many_deletions,
            notify_many_deletions_threshold=notify_many_deletions_threshold,
        )
        self.base_url = "https://bybit-exchange.github.io/docs/v5/intro"
        self.docs_domain = "bybit-exchange.github.io"
        self.max_pages = max_pages
        self.max_announcement_pages = max(
            1, min(int(max_announcement_pages), self.ANNOUNCEMENTS_MAX_PAGES)
        )
        self.monitor_docs = monitor_docs
        self.monitor_announcements = monitor_announcements

        # Announcements are limited to the current and previous year, like
        # the other changelog monitors
        current_year = datetime.now(timezone.utc).year
        self.years_to_monitor = [current_year, current_year - 1]

        # Announcement content keyed by section id (filled during discovery)
        self._announcement_content: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cutoff_ms(self) -> int:
        """
        Get the earliest publish time to monitor: 1 January (UTC) of the
        earliest monitored year, in milliseconds.
        """
        cutoff = datetime(min(self.years_to_monitor), 1, 1, tzinfo=timezone.utc)
        return int(cutoff.timestamp() * 1000)

    def _is_announcement_section(self, section_id: str) -> bool:
        """Check whether a section id refers to an announcement."""
        return section_id.startswith(self.ANNOUNCEMENTS_SITE)

    def _announcements_page_url(self) -> str:
        """Get the human-readable announcements page."""
        return f"{self.ANNOUNCEMENTS_SITE}/{self.ANNOUNCEMENTS_LOCALE}/"

    # ------------------------------------------------------------------
    # Documentation site crawl
    # ------------------------------------------------------------------

    def _discover_doc_pages(self) -> Dict[str, str]:
        """
        Discover documentation pages by crawling from the base URL.

        Each page is treated as a "section" where the URL is the section ID.

        Returns:
            Dict of url -> page_title
        """
        visited = set()
        to_visit = {self.base_url}
        discovered = {}

        self.logger.info(f"Discovering Bybit V5 API documentation from {self.base_url}...")

        while to_visit and len(discovered) < self.max_pages:
            url = to_visit.pop()

            if url in visited:
                continue

            visited.add(url)

            try:
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                # Extract page title
                title_elem = soup.find("h1")
                title = (
                    title_elem.get_text(strip=True)
                    if title_elem
                    else url.split("/")[-1]
                )

                # Add current page to discovered
                discovered[url] = title
                self.logger.debug(f"Discovered ({len(discovered)}/{self.max_pages}): {title}")

                # Find all documentation links
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    absolute_url = urljoin(url, href)

                    # Parse URL
                    parsed = urlparse(absolute_url)

                    # Only follow links within the v5 docs
                    if (
                        parsed.netloc == self.docs_domain
                        and "/docs/v5/" in parsed.path
                        and absolute_url not in visited
                        and len(discovered) < self.max_pages
                    ):
                        # Remove fragments and query params
                        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        to_visit.add(clean_url)

                time.sleep(0.5)  # Be polite to the server

            except Exception as e:
                self.logger.error(f"Error discovering from {url}: {e}")

        self.logger.info(f"Discovered {len(discovered)} pages")
        return discovered

    def _fetch_doc_page(self, url: str) -> Tuple[str, str]:
        """
        Fetch a documentation page and return its content and hash.

        Args:
            url: The page URL

        Returns:
            Tuple of (content, hash)
        """
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove non-content elements
            for element in soup(
                ["script", "style", "nav", "footer", "header", "aside"]
            ):
                element.decompose()

            # Remove navigation menus
            for nav_class in ["navbar", "menu", "sidebar", "toc"]:
                for element in soup.find_all(
                    class_=lambda x: x and nav_class in x.lower()
                ):
                    element.decompose()

            # Get main content
            main_content = soup.find("main") or soup.find("article") or soup
            content = main_content.get_text(separator="\n", strip=True)
            content_hash = self.get_page_hash(content)

            return content, content_hash
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return "", ""

    # ------------------------------------------------------------------
    # Announcements
    # ------------------------------------------------------------------

    def _discover_announcements(self) -> Dict[str, str]:
        """
        Discover recent announcements from the public API.

        Each announcement's article URL is its section id. Content (title and
        description) is cached so fetch_section_content does not call the API
        again.

        Returns:
            Dict of section_id -> title
        """
        sections = {}
        cutoff_ms = self._cutoff_ms()
        self.logger.info(
            f"Fetching the newest {self.max_announcement_pages} page(s) of announcements "
            f"from {self.ANNOUNCEMENTS_API}..."
        )

        # The API returns announcements newest first (roughly: pinned items can
        # sit slightly out of order), so page forward until
        # max_announcement_pages is reached, the list runs out, or a whole page
        # is older than the cutoff
        announcements = []
        more_in_range = False
        try:
            for page in range(1, self.max_announcement_pages + 1):
                params = {
                    "locale": self.ANNOUNCEMENTS_LOCALE,
                    "page": page,
                    "limit": self.ANNOUNCEMENTS_PAGE_SIZE,
                }
                response = self.session.get(self.ANNOUNCEMENTS_API, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
                if data.get("retCode") != 0:
                    raise ValueError(
                        f"API returned retCode {data.get('retCode')}: {data.get('retMsg')}"
                    )
                batch = (data.get("result") or {}).get("list") or []
                announcements.extend(batch)

                if len(batch) < self.ANNOUNCEMENTS_PAGE_SIZE:
                    break
                if all(int(a.get("publishTime") or 0) < cutoff_ms for a in batch):
                    break
            else:
                more_in_range = True
        except Exception as e:
            self.logger.error(f"  Error fetching announcements: {e}")
            if not announcements:
                return sections

        if more_in_range:
            self.logger.info(
                f"  Older announcements within the monitored range exist beyond the "
                f"{self.max_announcement_pages} page(s) fetched and are not tracked"
            )

        skipped = 0
        for announcement in announcements:
            section_id = announcement.get("url") or ""
            if not self._is_announcement_section(section_id):
                self.logger.warning(f"  Skipping announcement with unexpected url: {section_id!r}")
                continue

            published_ms = int(announcement.get("publishTime") or 0)
            if published_ms < cutoff_ms:
                skipped += 1
                continue

            published = datetime.fromtimestamp(published_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
            title = " ".join((announcement.get("title") or "").split())
            description = (announcement.get("description") or "").strip()

            sections[section_id] = f"{published} {title}"
            self._announcement_content[section_id] = f"{title}\n{description}"
            self.logger.debug(f"  Found announcement: {published} {title}")

        self.logger.info(
            f"  Discovered {len(sections)} recent announcements"
            + (f" ({skipped} older announcements skipped)" if skipped else "")
        )
        return sections

    # ------------------------------------------------------------------
    # BaseDocMonitor interface
    # ------------------------------------------------------------------

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover all sections: documentation pages and announcements.

        Returns:
            Dict of section_id -> title
        """
        sections = {}

        if self.monitor_docs:
            sections.update(self._discover_doc_pages())

        if self.monitor_announcements:
            sections.update(self._discover_announcements())

        self.logger.info(f"Discovered {len(sections)} total sections to monitor")
        return sections

    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Fetch a section's content and return its content and hash.

        Args:
            section_id: Documentation page URL or announcement URL

        Returns:
            Tuple of (content, hash)
        """
        if self._is_announcement_section(section_id):
            content = self._announcement_content.get(section_id, "")
            if not content:
                return "", ""
            return content, self.get_page_hash(content)

        return self._fetch_doc_page(section_id)

    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific section.

        For Bybit, the section_id is already the URL.

        Args:
            section_id: The page or announcement URL

        Returns:
            The URL (same as section_id)
        """
        return section_id

    def get_section_label(self, section_id: str) -> str:
        """Label announcements; documentation pages keep no label."""
        if self._is_announcement_section(section_id):
            return "ANNOUNCEMENT"
        return ""

    def get_telegram_footer(self) -> str:
        """Get the footer for Telegram messages."""
        message = ""
        if self.monitor_docs:
            message += f"\n📚 Documentation: [Bybit V5 Docs]({self.base_url})"
        if self.monitor_announcements:
            message += (
                f"\n📣 Announcements: [Bybit Announcements]({self._announcements_page_url()})"
            )
        return message

    def print_summary_footer(self):
        """Print footer for summary."""
        self.logger.info("View full documentation at:")
        self.logger.info(f"  Bybit: {self.base_url}")
        if self.monitor_announcements:
            self.logger.info(f"  Announcements: {self._announcements_page_url()}")


def main():
    """Main execution function."""
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Bybit", default_storage_file="state/bybit_docs_state.json"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1000,
        help="Maximum number of pages to discover (default: 1000)",
    )
    parser.add_argument(
        "--max-announcement-pages",
        type=int,
        default=1,
        help="Pages of 50 announcements to fetch, newest first (default: 1)",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Do not crawl the V5 API documentation",
    )
    parser.add_argument(
        "--no-announcements",
        action="store_true",
        help="Do not monitor platform announcements",
    )
    args = parser.parse_args()

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

    # Create monitor
    monitor = BybitDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        telegram_admin_chat_id=BaseDocMonitor.get_telegram_admin_chat_id(args),
        max_pages=args.max_pages,
        max_announcement_pages=args.max_announcement_pages,
        monitor_docs=not args.no_docs,
        monitor_announcements=not args.no_announcements,
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
