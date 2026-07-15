#!/usr/bin/env python3
"""
Deribit API Documentation Change Monitor with Telegram Notifications

This script scrapes the Deribit API documentation website and tracks changes
by crawling articles, API reference, and subscription pages.

Automatically sends Telegram notifications when changes are detected.
"""

from bs4 import BeautifulSoup
from typing import Dict, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime
import time
from .base_monitor import BaseDocMonitor


class DeribitDocMonitor(BaseDocMonitor):
    """Monitor for Deribit documentation across articles, API reference, and subscriptions."""

    # URL patterns to monitor
    SECTIONS_TO_MONITOR = [
        "articles/",
        "api-reference/",
        "subscriptions/",
    ]

    def __init__(
        self,
        storage_file: str = "state/deribit_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        max_pages: int = 1000,
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
            max_pages: Maximum number of pages to discover
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

    def discover_sections(self) -> Dict[str, str]:
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

        self.logger.info(f"Discovered {len(discovered)} total pages to monitor")

        return discovered

    def fetch_section_content(self, page_url: str) -> Tuple[str, str]:
        """
        Fetch a specific page's content and return its content and hash.

        Args:
            page_url: The page URL

        Returns:
            Tuple of (content, hash)
        """
        try:
            response = self.session.get(page_url, timeout=15)
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
            self.logger.error(f"  Error fetching page {page_url}: {e}")
            return "", ""

    def get_section_url(self, page_url: str) -> str:
        """
        Get the URL for a specific page.

        Args:
            page_url: The page URL

        Returns:
            The URL (same as page_url)
        """
        return page_url

    def get_section_label(self, section_id: str) -> str:
        """Get category label from page URL."""
        if "/articles/" in section_id:
            return "ARTICLES"
        elif "/api-reference/" in section_id:
            return "API"
        elif "/subscriptions/" in section_id:
            return "SUBSCRIPTIONS"
        return ""

    def get_telegram_footer(self) -> str:
        """Get the footer for Telegram messages."""
        return f"\n📚 Documentation: [Deribit Docs]({self.base_url})"

    def print_summary_footer(self):
        """Print footer for summary."""
        self.logger.info("View full documentation at:")
        self.logger.info(f"  Deribit: {self.base_url}")


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
    args = parser.parse_args()

    # Get Telegram credentials
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor
    monitor = DeribitDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        max_pages=args.max_pages,
        notify_additions=notify_additions,
        notify_modifications=notify_modifications,
        notify_deletions=notify_deletions,
    )

    # Check for changes
    changes = monitor.check_for_changes(save_content=args.save_content)

    # Print summary
    monitor.print_summary(changes)

    # Send Telegram notification if changes detected
    monitor.send_telegram(changes)


if __name__ == "__main__":
    main()
