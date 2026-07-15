#!/usr/bin/env python3
"""
Lighter API Documentation Change Monitor with Telegram Notifications

This script monitors Lighter API documentation (Docs and API Reference) and tracks changes
by storing page hashes for comparison.

Automatically sends Telegram notifications when changes are detected.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Tuple
from .base_monitor import BaseDocMonitor


class LighterDocMonitor(BaseDocMonitor):
    """Monitor for Lighter API documentation hosted on ReadMe.io."""

    BASE_URL = "https://apidocs.lighter.xyz"

    # Seed pages to scrape sidebar navigation from
    SEED_PAGES = {
        "docs": f"{BASE_URL}/docs/get-started",
        "reference": f"{BASE_URL}/reference/status",
    }

    def __init__(
        self,
        storage_file: str = "state/lighter_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        monitor_docs: bool = True,
        monitor_reference: bool = True,
        notify_additions: bool = True,
        notify_modifications: bool = True,
        notify_deletions: bool = False,
    ):
        """
        Initialize the documentation monitor.

        Args:
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            monitor_docs: Whether to monitor guide/docs pages
            monitor_reference: Whether to monitor API reference pages
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
        """
        super().__init__(
            exchange_name="Lighter",
            storage_file=storage_file,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=telegram_chat_id,
            notify_additions=notify_additions,
            notify_modifications=notify_modifications,
            notify_deletions=notify_deletions,
        )

        self.monitor_docs = monitor_docs
        self.monitor_reference = monitor_reference

        # Pattern to match "Updated\nX days/weeks/months/years ago" text
        # This avoids false positives from relative timestamp changes
        self._updated_pattern = re.compile(
            r"Updated\n\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago(?:\nDid this page help you\?\nYes\nNo)?",
            re.IGNORECASE,
        )

    def _discover_sidebar_links(self, seed_url: str, prefix: str) -> Dict[str, str]:
        """
        Fetch a seed page and extract all sidebar navigation links matching a prefix.

        Args:
            seed_url: URL to fetch for sidebar discovery
            prefix: URL path prefix to filter links (e.g., "/docs/", "/reference/")

        Returns:
            Dict of full_url -> page_title
        """
        pages = {}

        try:
            response = self.session.get(seed_url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # ReadMe.io sidebar links are <a> tags with hrefs starting with the prefix
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")

                # Match links like /docs/get-started or /reference/status
                if not href.startswith(prefix):
                    continue

                title = link.get_text(strip=True)

                # Skip empty titles, overly long ones, or pure navigation elements
                if not title or len(title) > 150:
                    continue

                full_url = f"{self.BASE_URL}{href}"

                # Avoid duplicates (keep first occurrence which has better title)
                if full_url not in pages:
                    pages[full_url] = title
                    self.logger.debug(f"  Found: {title} ({href})")

        except Exception as e:
            self.logger.error(f"  Error fetching sidebar from {seed_url}: {e}")

        return pages

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover documentation pages by scraping sidebar navigation.

        Returns:
            Dict of page_url -> page_title
        """
        all_sections = {}

        if self.monitor_docs:
            self.logger.info(
                f"Discovering docs pages from {self.SEED_PAGES['docs']}..."
            )
            docs_pages = self._discover_sidebar_links(
                self.SEED_PAGES["docs"], "/docs/"
            )
            all_sections.update(docs_pages)
            self.logger.info(f"  Discovered {len(docs_pages)} docs pages")

        if self.monitor_reference:
            self.logger.info(
                f"Discovering reference pages from {self.SEED_PAGES['reference']}..."
            )
            ref_pages = self._discover_sidebar_links(
                self.SEED_PAGES["reference"], "/reference/"
            )
            all_sections.update(ref_pages)
            self.logger.info(f"  Discovered {len(ref_pages)} reference pages")

        self.logger.info(f"Total pages to monitor: {len(all_sections)}")
        return all_sections

    def fetch_section_content(self, page_url: str) -> Tuple[str, str]:
        """
        Fetch a specific page's content and return its content and hash.

        Args:
            page_url: The full page URL

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

            # Get main content
            main_content = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", class_=lambda x: x and "content" in x.lower())
                or soup
            )

            content = main_content.get_text(separator="\n", strip=True)

            # Clean content to remove dynamic "Updated X days ago" text
            # before hashing to avoid false positives
            cleaned_content = self._updated_pattern.sub("", content)
            content_hash = self.get_page_hash(cleaned_content)

            return content, content_hash

        except Exception as e:
            self.logger.error(f"  Error fetching page {page_url}: {e}")
            return "", ""

    def get_section_url(self, page_url: str) -> str:
        """
        Get the URL for a specific page.

        Args:
            page_url: The full page URL

        Returns:
            The URL (same as page_url)
        """
        return page_url

    def get_section_label(self, section_id: str) -> str:
        """Get category label from page URL."""
        if "/reference/" in section_id:
            return "API"
        elif "/docs/" in section_id:
            return "DOCS"
        return ""

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages with documentation links.

        Returns:
            Footer string with documentation links
        """
        message = "\n📚 Documentation:\n"
        if self.monitor_docs:
            message += f"  • [Docs]({self.SEED_PAGES['docs']})\n"
        if self.monitor_reference:
            message += f"  • [API Reference]({self.SEED_PAGES['reference']})"
        return message

    def print_summary_footer(self):
        """Print footer for summary with documentation URLs."""
        self.logger.info("View documentation at:")
        if self.monitor_docs:
            self.logger.info(f"  Docs: {self.SEED_PAGES['docs']}")
        if self.monitor_reference:
            self.logger.info(f"  API Reference: {self.SEED_PAGES['reference']}")


def main():
    """Main execution function."""
    # Create argument parser using base class helper
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Lighter",
        default_storage_file="state/lighter_docs_state.json",
    )

    # Add Lighter-specific arguments
    parser.add_argument(
        "--docs-only",
        action="store_true",
        help="Monitor only guide/docs pages",
    )
    parser.add_argument(
        "--reference-only",
        action="store_true",
        help="Monitor only API reference pages",
    )

    args = parser.parse_args()

    # Determine which sections to monitor
    only_flags = args.docs_only or args.reference_only
    monitor_docs = args.docs_only if only_flags else True
    monitor_reference = args.reference_only if only_flags else True

    # Get Telegram credentials using base class helper
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor instance
    monitor = LighterDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        monitor_docs=monitor_docs,
        monitor_reference=monitor_reference,
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
