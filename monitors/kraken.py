#!/usr/bin/env python3
"""
Kraken API Documentation Change Monitor with Telegram Notifications

This script monitors Kraken API changelog page and tracks changes
by storing the page hash for comparison.

Automatically sends Telegram notifications when changes are detected.
"""

from bs4 import BeautifulSoup
from typing import Dict, Tuple
from .base_monitor import BaseDocMonitor


class KrakenDocMonitor(BaseDocMonitor):
    def __init__(
        self,
        storage_file: str = "state/kraken_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        notify_additions: bool = True,
        notify_modifications: bool = True,
        notify_deletions: bool = False,
        notify_no_sections: bool = True,
        notify_many_deletions: bool = True,
        notify_many_deletions_threshold: float = 0.2
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
            exchange_name="Kraken",
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

        self.changelog_url = "https://docs.kraken.com/api/docs/change-log"

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover sections to monitor. For Kraken, we monitor the entire changelog as one section.

        Returns:
            Dict with single entry: changelog URL -> title
        """
        self.logger.info(f"Setting up monitoring for {self.changelog_url}...")

        # Return the changelog URL as a single section to monitor
        sections = {
            self.changelog_url: "Kraken API Changelog"
        }

        self.logger.info(f"  Monitoring: Kraken API Changelog (entire page)")

        return sections

    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Fetch the changelog page content and return its content and hash.

        Args:
            section_id: The section ID (changelog URL)

        Returns:
            Tuple of (content, hash)
        """
        try:
            response = self.session.get(section_id, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove non-content elements
            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.decompose()

            # Remove navigation elements by class, but be careful not to remove content
            # Only remove elements that are clearly navigation (not main content areas)
            for element in soup.find_all(class_=lambda x: x and "navbar" in x.lower()):
                element.decompose()

            # Try to find the main content area - Docusaurus uses specific patterns
            main_content = (
                soup.find("article")
                or soup.find("main")
                or soup.find("div", class_=lambda x: x and "markdown" in x.lower())
                or soup.body
                or soup
            )

            content = main_content.get_text(separator="\n", strip=True)
            content_hash = self.get_page_hash(content)

            return content, content_hash

        except Exception as e:
            self.logger.error(f"  Error fetching changelog: {e}")
            return "", ""

    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific section.

        Args:
            section_id: The section identifier (changelog URL)

        Returns:
            The changelog URL
        """
        return section_id

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages with changelog link.

        Returns:
            Footer string with changelog link
        """
        return f"\n📚 Changelog: [Kraken API Changelog]({self.changelog_url})"

    def print_summary_footer(self):
        """Print footer for summary with changelog URL."""
        self.logger.info("View changelog at:")
        self.logger.info(f"  Kraken: {self.changelog_url}")


def main():
    """Main execution function."""
    # Create argument parser using base class helper
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Kraken", default_storage_file="state/kraken_docs_state.json"
    )

    args = parser.parse_args()

    # Get Telegram credentials using base class helper
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor instance
    monitor = KrakenDocMonitor(
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
