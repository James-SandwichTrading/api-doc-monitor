#!/usr/bin/env python3
"""
OKX API Changelog Monitor with Telegram Notifications

This script monitors OKX API changelog and tracks changes by storing
section hashes for comparison.

Automatically sends Telegram notifications when changes are detected.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Tuple
from .base_monitor import BaseDocMonitor


class OKXDocMonitor(BaseDocMonitor):
    """Monitor for OKX API changelog."""

    def __init__(
        self,
        storage_file: str = "state/okx_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        base_url: str = "https://www.okx.com/docs-v5/log_en/",
        notify_additions: bool = True,
        notify_modifications: bool = True,
        notify_deletions: bool = False,
        notify_no_sections: bool = True,
        notify_many_deletions: bool = True,
        notify_many_deletions_threshold: float = 0.2
    ):
        """
        Initialize the changelog monitor.

        Args:
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            base_url: Base URL for the API changelog
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """
        super().__init__(
            exchange_name="OKX",
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

        self.base_url = base_url.rstrip("/")

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover subsections under "Upcoming Changes" only.

        Returns:
            Dict of url -> section_title
        """
        self.logger.info(f"Discovering upcoming changes from {self.base_url}...")

        sections = {}

        try:
            response = self.session.get(self.base_url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Find the "Upcoming Changes" section
            upcoming_section = soup.find(id="upcoming-changes")

            if not upcoming_section:
                self.logger.warning("  Warning: Could not find 'upcoming-changes' section")
                return sections

            # Get the heading level of "Upcoming Changes"
            upcoming_level = int(upcoming_section.name[1]) if upcoming_section.name.startswith('h') else 2

            # Find all subsequent headings that are subsections of "Upcoming Changes"
            # Stop when we hit a heading of the same or higher level (e.g., a date section)
            for sibling in upcoming_section.find_next_siblings():
                # If it's a heading
                if sibling.name and sibling.name.startswith('h'):
                    sibling_level = int(sibling.name[1])

                    # Stop if we've reached the next top-level section (same or higher level)
                    if sibling_level <= upcoming_level:
                        break

                    # This is a subsection under "Upcoming Changes"
                    section_id = sibling.get("id")
                    if section_id:
                        section_title = sibling.get_text(strip=True)
                        # Use full URL with fragment as the key
                        full_url = f"{self.base_url}#{section_id}"
                        sections[full_url] = section_title
                        self.logger.debug(f"  Found: {section_title} (#{section_id})")

            self.logger.info(f"Discovered {len(sections)} upcoming changes to monitor")

        except Exception as e:
            self.logger.error(f"  Error discovering sections: {e}")
            self.logger.warning("  Falling back to empty section list")

        return sections

    def fetch_section_content(self, section_url: str) -> Tuple[str, str]:
        """
        Fetch a specific section's content and return its content and hash.

        Args:
            section_url: The full section URL with fragment

        Returns:
            Tuple of (content, hash)
        """
        # Extract the section ID from the URL fragment
        section_id = section_url.split("#")[-1] if "#" in section_url else None

        if not section_id:
            return "", ""

        try:
            # Fetch the base page (without fragment)
            base_url = section_url.split("#")[0]
            response = self.session.get(base_url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Find the section by ID
            section = soup.find(id=section_id)

            if not section:
                return "", ""

            # Get all content until the next heading of same or higher level
            content_parts = [section.get_text(strip=True)]
            current_level = section.name  # h1, h2, h3, etc.

            # Traverse siblings to get content until next heading of same/higher level
            for sibling in section.find_next_siblings():
                # Stop at the next heading of same or higher level
                if sibling.name in ["h1", "h2", "h3", "h4", "h5"]:
                    # Extract heading level number (h1 -> 1, h2 -> 2, etc.)
                    sibling_level = int(sibling.name[1])
                    current_level_num = int(current_level[1])

                    if sibling_level <= current_level_num:
                        break

                # Get text from this element
                if sibling.name not in ["script", "style", "nav", "footer", "header"]:
                    text = sibling.get_text(separator=" ", strip=True)
                    if text:
                        content_parts.append(text)

            content = "\n".join(content_parts)
            content_hash = self.get_page_hash(content)

            return content, content_hash

        except Exception as e:
            self.logger.error(f"  Error fetching section {section_id}: {e}")
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

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages with changelog links.

        Returns:
            Footer string with changelog links
        """
        return f"\n📚 Changelog: [OKX API Changelog]({self.base_url})"

    def print_summary_footer(self):
        """Print footer for summary with changelog URLs."""
        self.logger.info("View changelog at:")
        self.logger.info(f"  OKX: {self.base_url}")


def main():
    """Main execution function."""
    # Create argument parser using base class helper
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="OKX",
        default_storage_file="state/okx_docs_state.json"
    )

    args = parser.parse_args()

    # Get Telegram credentials using base class helper
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor instance
    monitor = OKXDocMonitor(
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
