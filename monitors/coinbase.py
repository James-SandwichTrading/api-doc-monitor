#!/usr/bin/env python3
"""
Coinbase CDP Documentation Change Monitor with Telegram Notifications

This script monitors Coinbase CDP documentation (Exchange, International Exchange,
Prime, and Derivatives) and tracks changes by storing page hashes for comparison.

Automatically sends Telegram notifications when changes are detected.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Tuple
from .base_monitor import BaseDocMonitor


class CoinbaseDocMonitor(BaseDocMonitor):
    def __init__(
        self,
        storage_file: str = "state/coinbase_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        notify_additions: bool = True,
        notify_modifications: bool = True,
        notify_deletions: bool = False,
        notify_no_sections: bool = True,
        notify_many_deletions: bool = True,
        notify_many_deletions_threshold: float = 0.2,
    ):
        """
        Initialize the documentation monitor.

        Args:
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """
        super().__init__(
            exchange_name="Coinbase",
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

        # Monitor multiple Coinbase documentation pages
        self.urls = {
            "exchange_upcoming": {
                "url": "https://docs.cdp.coinbase.com/exchange/changes/upcoming-changes",
                "title": "Exchange Upcoming Changes"
            },
            "intl_exchange_upcoming": {
                "url": "https://docs.cdp.coinbase.com/international-exchange/changes/upcoming-changes",
                "title": "International Exchange Upcoming Changes"
            },
            "prime_upcoming": {
                "url": "https://docs.cdp.coinbase.com/prime/changes/upcoming-changes",
                "title": "Prime Upcoming Changes"
            },
            "derivatives_changelog": {
                "url": "https://docs.cdp.coinbase.com/derivatives/changes/changelog",
                "title": "Derivatives Changelog"
            }
        }

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover sections to monitor. Returns all configured Coinbase documentation pages.

        Returns:
            Dict of url -> section_title
        """
        self.logger.info(f"Setting up monitoring for Coinbase documentation pages...")

        sections = {}
        for page_type, page_info in self.urls.items():
            # Use full URL as the key
            sections[page_info["url"]] = page_info["title"]
            self.logger.info(f"  Monitoring: {page_info['title']}")

        return sections

    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Fetch the documentation page content and return its content and hash.

        Args:
            section_id: The section ID (full URL)

        Returns:
            Tuple of (content, hash)
        """
        url = section_id

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove non-content elements
            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
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
            self.logger.error(f"  Error fetching {url}: {e}")
            return "", ""

    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific section.

        Args:
            section_id: The section identifier (full URL)

        Returns:
            The docs URL (same as section_id)
        """
        return section_id

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages with docs links.

        Returns:
            Footer string with docs links
        """
        message = "\n📚 Documentation:\n"
        for page_type, page_info in self.urls.items():
            # Shorten labels for Telegram
            label = page_info["title"].replace("Upcoming Changes", "").replace("Changelog", "").strip()
            if not label:
                label = page_info["title"]
            message += f"  • [{label}]({page_info['url']})\n"
        return message.rstrip()

    def print_summary_footer(self):
        """Print footer for summary with docs URLs."""
        self.logger.info("View documentation at:")
        for page_type, page_info in self.urls.items():
            self.logger.info(f"  {page_info['title']}: {page_info['url']}")


def main():
    """Main execution function."""
    # Create argument parser using base class helper
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Coinbase", default_storage_file="state/coinbase_docs_state.json"
    )

    args = parser.parse_args()

    # Get Telegram credentials using base class helper
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor instance
    monitor = CoinbaseDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
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
