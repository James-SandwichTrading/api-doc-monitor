#!/usr/bin/env python3
"""
Deribit API Documentation Change Monitor with Telegram Notifications

This script monitors three Deribit sources:

1. The documentation site (https://docs.deribit.com) - crawls articles, API
   reference and subscription pages and tracks each page as a section.
2. The API changelogs (https://docs.deribit.com/changelogs/{jsonrpc,fix,starbase})
   - each dated release entry is tracked as its own section, limited to the
   current and previous year so new releases show up as additions.
3. Platform announcements from the public API
   (https://www.deribit.com/api/v2/public/get_announcements) - each
   announcement is tracked as its own section, limited to the current and
   previous year.

Automatically sends Telegram notifications when changes are detected.
"""

from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime
import re
import time
from .base_monitor import BaseDocMonitor


class DeribitDocMonitor(BaseDocMonitor):
    """Monitor for Deribit documentation, API changelogs and announcements."""

    # URL patterns to monitor on the documentation site
    SECTIONS_TO_MONITOR = [
        "articles/",
        "api-reference/",
        "subscriptions/",
    ]

    # Changelog pages: path name -> display name
    CHANGELOGS = {
        "jsonrpc": "JSON-RPC",
        "fix": "FIX",
        "starbase": "Starbase",
    }

    ANNOUNCEMENTS_API = "https://www.deribit.com/api/v2/public/get_announcements"

    # Maximum the announcements API returns per request, and how many pages
    # to walk back through at most
    ANNOUNCEMENTS_MAX_COUNT = 50
    ANNOUNCEMENTS_MAX_PAGES = 20

    def __init__(
        self,
        storage_file: str = "state/deribit_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        max_pages: int = 1000,
        monitor_docs: bool = True,
        monitor_changelogs: bool = True,
        monitor_announcements: bool = True,
        notify_additions: bool = True,
        notify_modifications: bool = False,
        notify_deletions: bool = False,
        notify_no_sections: bool = True,
        notify_many_deletions: bool = True,
        notify_many_deletions_threshold: float = 0.2,
    ):
        """
        Initialize the Deribit documentation monitor.

        Args:
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            max_pages: Maximum number of documentation pages to discover
            monitor_docs: Whether to crawl the documentation site pages
            monitor_changelogs: Whether to monitor the API changelog entries
            monitor_announcements: Whether to monitor platform announcements
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """
        super().__init__(
            exchange_name="Deribit",
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
        self.base_url = "https://docs.deribit.com"
        self.max_pages = max_pages
        self.monitor_docs = monitor_docs
        self.monitor_changelogs = monitor_changelogs
        self.monitor_announcements = monitor_announcements

        # Changelog entries and announcements are limited to the current and
        # previous year, like the other changelog monitors
        current_year = datetime.now().year
        self.years_to_monitor = [current_year, current_year - 1]

        # Parsed changelog pages (url -> soup, or None if the fetch failed)
        self._changelog_cache: Dict[str, Optional[BeautifulSoup]] = {}

        # Announcement content keyed by section id (filled during discovery)
        self._announcement_content: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cutoff_date(self) -> datetime:
        """
        Get the earliest date to monitor: 1 January of the earliest monitored year.

        Returns:
            Cutoff datetime
        """
        return datetime(min(self.years_to_monitor), 1, 1)

    def _changelog_url(self, name: str) -> str:
        """Get the URL of a changelog page."""
        return f"{self.base_url}/changelogs/{name}"

    def _is_changelog_section(self, section_id: str) -> bool:
        """Check whether a section id refers to a changelog entry."""
        return section_id.startswith(f"{self.base_url}/changelogs/") and "#" in section_id

    def _is_announcement_section(self, section_id: str) -> bool:
        """Check whether a section id refers to an announcement."""
        return section_id.startswith(self.ANNOUNCEMENTS_API)

    # ------------------------------------------------------------------
    # Documentation site crawl
    # ------------------------------------------------------------------

    def _is_valid_doc_page(self, url: str) -> bool:
        """
        Check if a URL is a valid documentation page to monitor.

        Args:
            url: URL to check

        Returns:
            True if the URL matches one of our monitoring patterns
        """
        parsed = urlparse(url)
        path = parsed.path

        # Check if the path starts with any of our monitored sections
        for section in self.SECTIONS_TO_MONITOR:
            if f"/{section}" in path:
                return True

        return False

    def _discover_links_from_page(
        self, url: str, discovered: Dict[str, str], visited: set
    ):
        """
        Recursively discover links from a page.

        Args:
            url: URL to fetch
            discovered: Dictionary to populate with discovered pages
            visited: Set of already visited URLs to avoid loops
        """
        if url in visited or len(discovered) >= self.max_pages:
            return

        visited.add(url)

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Get page title
            title_elem = soup.find("h1")
            title = (
                title_elem.get_text(strip=True) if title_elem else url.split("/")[-1]
            )

            # Add current page if it's a valid doc page
            if self._is_valid_doc_page(url):
                # Use the path as the key (remove base URL)
                page_path = url.replace(self.base_url, "").strip("/")
                if page_path and page_path not in discovered.values():
                    discovered[url] = title
                    self.logger.debug(f"  Found: {title} ({page_path})")

            # Find all links
            all_links = soup.find_all("a", href=True)

            for link in all_links:
                href = link.get("href", "")

                # Skip external links, anchors, and empty hrefs
                if (
                    not href
                    or href.startswith("http")
                    and not href.startswith(self.base_url)
                ):
                    continue

                # Convert to absolute URL
                absolute_url = urljoin(url, href)

                # Remove fragments and query params
                parsed = urlparse(absolute_url)
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                # Check if this is a valid doc page we should follow
                if (
                    clean_url not in visited
                    and self._is_valid_doc_page(clean_url)
                    and len(discovered) < self.max_pages
                ):
                    self._discover_links_from_page(clean_url, discovered, visited)

            time.sleep(0.3)  # Rate limiting

        except Exception as e:
            self.logger.error(f"  Error fetching {url}: {e}")

    def _discover_doc_pages(self) -> Dict[str, str]:
        """
        Discover documentation pages by crawling the documentation site.

        Returns:
            Dict of url -> page_title
        """
        self.logger.info(f"Discovering documentation pages from {self.base_url}...")

        discovered = {}
        visited = set()

        # Start by discovering from each main section
        for section in self.SECTIONS_TO_MONITOR:
            section_url = f"{self.base_url}/{section}"
            self.logger.info(f"Crawling section: {section}")
            self._discover_links_from_page(section_url, discovered, visited)

        self.logger.info(f"Discovered {len(discovered)} documentation pages to monitor")

        return discovered

    # ------------------------------------------------------------------
    # Changelogs
    # ------------------------------------------------------------------

    def _fetch_changelog_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch and parse a changelog page, caching the result.

        Args:
            url: Changelog page URL

        Returns:
            Parsed page, or None if it could not be fetched
        """
        if url in self._changelog_cache:
            return self._changelog_cache[url]

        soup = None
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception as e:
            self.logger.error(f"  Error fetching changelog {url}: {e}")

        self._changelog_cache[url] = soup
        return soup

    @staticmethod
    def _changelog_entry_label(entry) -> str:
        """
        Get the label of a changelog entry (e.g. "Release 18.08.2026").

        The entry is a div.update whose first child div holds the label.
        Mintlify inserts a zero-width space before the label, which is stripped.

        Args:
            entry: The div.update element

        Returns:
            Label text
        """
        label_elem = entry.find("div")
        text = label_elem.get_text(" ", strip=True) if label_elem else ""
        return text.replace("\u200b", "").strip()

    @staticmethod
    def _parse_label_date(label: str) -> Optional[datetime]:
        """
        Parse the dd.mm.yyyy date from a changelog entry label.

        Args:
            label: Entry label, e.g. "Release 18.08.2026" or "Starbase Update 25.08.2026"

        Returns:
            Parsed date, or None if the label has no recognisable date
        """
        match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", label)
        if not match:
            return None
        day, month, year = (int(g) for g in match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    def _discover_changelog_entries(self) -> Dict[str, str]:
        """
        Discover recent entries from the changelog pages.

        Each entry is a div.update with an id that doubles as the URL fragment.
        Entries older than the cutoff are skipped; entries whose label has no
        date are kept.

        Returns:
            Dict of url#fragment -> title
        """
        sections = {}
        cutoff = self._cutoff_date()
        self.logger.info(
            f"Discovering changelog entries from {cutoff.strftime('%Y-%m-%d')} onwards..."
        )

        for name, display_name in self.CHANGELOGS.items():
            url = self._changelog_url(name)
            self.logger.info(f"Fetching {display_name} changelog from {url}...")

            soup = self._fetch_changelog_page(url)
            if soup is None:
                continue

            found = 0
            skipped = 0
            for entry in soup.select("div.update[id]"):
                label = self._changelog_entry_label(entry)
                if not label:
                    continue

                entry_date = self._parse_label_date(label)
                if entry_date is not None and entry_date < cutoff:
                    skipped += 1
                    continue

                # Starbase labels already start with "Starbase"
                if label.lower().startswith(display_name.lower()):
                    title = label
                else:
                    title = f"{display_name}: {label}"

                section_id = f"{url}#{entry['id']}"
                sections[section_id] = title
                found += 1
                self.logger.debug(f"  Found changelog entry: {label}")

            self.logger.info(
                f"  Discovered {found} recent {display_name} changelog entries"
                + (f" ({skipped} older entries skipped)" if skipped else "")
            )

        return sections

    def _fetch_changelog_entry(self, section_id: str) -> Tuple[str, str]:
        """
        Get the content and hash of a changelog entry.

        Args:
            section_id: url#fragment of the entry

        Returns:
            Tuple of (content, hash)
        """
        url, fragment = section_id.rsplit("#", 1)
        soup = self._fetch_changelog_page(url)
        if soup is None:
            return "", ""

        entry = soup.find(id=fragment)
        if entry is None:
            self.logger.warning(f"  Changelog entry not found: {fragment}")
            return "", ""

        content = entry.get_text(separator="\n", strip=True).replace("\u200b", "").strip()
        return content, self.get_page_hash(content)

    # ------------------------------------------------------------------
    # Announcements
    # ------------------------------------------------------------------

    def _announcement_section_id(self, announcement: Dict) -> str:
        """
        Build the section id (and "View" link) for an announcement.

        The API returns announcements published strictly before
        start_timestamp, newest first, so start_timestamp = publication
        timestamp + 1 with count=1 returns exactly this announcement.

        Args:
            announcement: Announcement object from the API

        Returns:
            URL that returns just this announcement
        """
        start = int(announcement["publication_timestamp"]) + 1
        return f"{self.ANNOUNCEMENTS_API}?start_timestamp={start}&count=1"

    def _discover_announcements(self) -> Dict[str, str]:
        """
        Discover recent announcements from the public API.

        Content is cached so fetch_section_content does not call the API again.

        Returns:
            Dict of section_id -> title
        """
        sections = {}
        cutoff_ms = int(self._cutoff_date().timestamp() * 1000)
        self.logger.info(f"Fetching announcements from {self.ANNOUNCEMENTS_API}...")

        # The API returns at most 50 announcements per call, newest first, so
        # page back with start_timestamp until the cutoff is passed
        announcements = []
        start_timestamp = None
        try:
            for page in range(self.ANNOUNCEMENTS_MAX_PAGES):
                params = {"count": self.ANNOUNCEMENTS_MAX_COUNT}
                if start_timestamp is not None:
                    params["start_timestamp"] = start_timestamp
                response = self.session.get(self.ANNOUNCEMENTS_API, params=params, timeout=15)
                response.raise_for_status()
                batch = response.json().get("result") or []
                announcements.extend(batch)

                if len(batch) < self.ANNOUNCEMENTS_MAX_COUNT:
                    break
                oldest_ms = int(batch[-1].get("publication_timestamp") or 0)
                if oldest_ms < cutoff_ms:
                    break
                start_timestamp = oldest_ms
            else:
                self.logger.warning(
                    f"  Stopped after {self.ANNOUNCEMENTS_MAX_PAGES} pages of announcements; "
                    "older announcements within the monitored range may be missing"
                )
        except Exception as e:
            self.logger.error(f"  Error fetching announcements: {e}")
            if not announcements:
                return sections

        skipped = 0
        for announcement in announcements:
            published_ms = int(announcement.get("publication_timestamp") or 0)
            if published_ms < cutoff_ms:
                skipped += 1
                continue

            published = datetime.fromtimestamp(published_ms / 1000).strftime("%Y-%m-%d")
            title = " ".join((announcement.get("title") or "").split())
            body_html = announcement.get("body") or ""
            body = BeautifulSoup(body_html, "html.parser").get_text(separator="\n", strip=True)

            section_id = self._announcement_section_id(announcement)
            sections[section_id] = f"{published} {title}"
            self._announcement_content[section_id] = f"{title}\n{body}"
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
        Discover all sections: documentation pages, changelog entries and announcements.

        Returns:
            Dict of section_id -> title
        """
        sections = {}

        if self.monitor_docs:
            sections.update(self._discover_doc_pages())

        if self.monitor_changelogs:
            sections.update(self._discover_changelog_entries())

        if self.monitor_announcements:
            sections.update(self._discover_announcements())

        self.logger.info(f"Discovered {len(sections)} total sections to monitor")
        return sections

    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Fetch a section's content and return its content and hash.

        Args:
            section_id: Page URL, changelog url#fragment, or announcement URL

        Returns:
            Tuple of (content, hash)
        """
        try:
            if self._is_announcement_section(section_id):
                content = self._announcement_content.get(section_id, "")
                if not content:
                    return "", ""
                return content, self.get_page_hash(content)

            if self._is_changelog_section(section_id):
                return self._fetch_changelog_entry(section_id)

            response = self.session.get(section_id, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove non-content elements
            for element in soup(
                ["script", "style", "nav", "footer", "header", "aside"]
            ):
                element.decompose()

            # Remove navigation menus and sidebars
            for nav_class in ["navbar", "menu", "sidebar", "toc", "navigation"]:
                for element in soup.find_all(
                    class_=lambda x: x and nav_class in x.lower()
                ):
                    element.decompose()

            # Get main content - try different content containers
            main_content = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", class_=lambda x: x and "content" in x.lower())
                or soup
            )

            content = main_content.get_text(separator="\n", strip=True)
            content_hash = self.get_page_hash(content)

            return content, content_hash

        except Exception as e:
            self.logger.error(f"  Error fetching section {section_id}: {e}")
            return "", ""

    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific section.

        Args:
            section_id: The section identifier

        Returns:
            The URL (same as section_id)
        """
        return section_id

    def get_section_label(self, section_id: str) -> str:
        """Get category label from section id."""
        if self._is_announcement_section(section_id):
            return "ANNOUNCEMENT"
        elif self._is_changelog_section(section_id):
            return "CHANGELOG"
        elif "/articles/" in section_id:
            return "ARTICLES"
        elif "/api-reference/" in section_id:
            return "API"
        elif "/subscriptions/" in section_id:
            return "SUBSCRIPTIONS"
        return ""

    def get_telegram_footer(self) -> str:
        """Get the footer for Telegram messages."""
        message = f"\n📚 Documentation: [Deribit Docs]({self.base_url})"
        if self.monitor_changelogs:
            links = " | ".join(
                f"[{display_name}]({self._changelog_url(name)})"
                for name, display_name in self.CHANGELOGS.items()
            )
            message += f"\n📝 Changelogs: {links}"
        if self.monitor_announcements:
            message += (
                f"\n📣 Announcements: [Deribit Announcements]"
                f"({self.ANNOUNCEMENTS_API}?count={self.ANNOUNCEMENTS_MAX_COUNT})"
            )
        return message

    def print_summary_footer(self):
        """Print footer for summary."""
        self.logger.info("View full documentation at:")
        self.logger.info(f"  Deribit: {self.base_url}")
        if self.monitor_changelogs:
            for name, display_name in self.CHANGELOGS.items():
                self.logger.info(f"  {display_name} changelog: {self._changelog_url(name)}")
        if self.monitor_announcements:
            self.logger.info(f"  Announcements: {self.ANNOUNCEMENTS_API}?count={self.ANNOUNCEMENTS_MAX_COUNT}")


def main():
    """Main execution function."""
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Deribit", default_storage_file="state/deribit_docs_state.json"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1000,
        help="Maximum number of pages to discover (default: 1000)",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Do not crawl the documentation site pages",
    )
    parser.add_argument(
        "--no-changelogs",
        action="store_true",
        help="Do not monitor the API changelog entries",
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
    monitor = DeribitDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        max_pages=args.max_pages,
        monitor_docs=not args.no_docs,
        monitor_changelogs=not args.no_changelogs,
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
