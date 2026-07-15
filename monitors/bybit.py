#!/usr/bin/env python3
"""
Bybit V5 API Documentation Change Monitor with Telegram Notifications

This script monitors the Bybit V5 API documentation for changes by crawling
the documentation site and tracking each page's content with hash-based detection.

Automatically sends Telegram notifications when changes are detected.
"""

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
from typing import Dict, Set, Tuple
from .base_monitor import BaseDocMonitor


class BybitDocMonitor(BaseDocMonitor):
    def __init__(
        self,
        storage_file: str = "state/bybit_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        max_pages: int = 500,
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
            max_pages: Maximum number of pages to discover
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

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover documentation pages by crawling from the base URL.

        For Bybit, each page is treated as a "section" where the URL is the section ID.

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

    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Fetch a page's content and return its content and hash.

        For Bybit, the section_id is the page URL.

        Args:
            section_id: The page URL

        Returns:
            Tuple of (content, hash)
        """
        try:
            response = self.session.get(section_id, timeout=10)
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
            self.logger.error(f"Error fetching {section_id}: {e}")
            return "", ""

    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific section.

        For Bybit, the section_id is already the URL.

        Args:
            section_id: The page URL

        Returns:
            The URL (same as section_id)
        """
        return section_id

    def print_summary_footer(self):
        """Print footer for summary."""
        self.logger.info(f"View full documentation at: {self.base_url}")


def main():
    """Main execution function."""
    import argparse

    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Bybit", default_storage_file="state/bybit_docs_state.json"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=500,
        help="Maximum number of pages to discover (default: 500)",
    )
    args = parser.parse_args()

    # Get Telegram credentials
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor
    monitor = BybitDocMonitor(
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
