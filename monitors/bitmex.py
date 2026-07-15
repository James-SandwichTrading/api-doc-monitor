#!/usr/bin/env python3
"""
BitMEX Product Updates Monitor with Telegram Notifications

This script monitors BitMEX Product Updates via RSS feed and tracks changes
by storing update titles, dates, and hashes for comparison.

Automatically sends Telegram notifications when changes are detected.
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Tuple
from .base_monitor import BaseDocMonitor


class BitmexDocMonitor(BaseDocMonitor):
    def __init__(
        self,
        storage_file: str = "state/bitmex_docs_state.json",
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
            exchange_name="BitMEX",
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

        self.rss_feed_url = "https://www.bitmex.com/blog/marketing/rss/feed.xml"
        self.blog_url = "https://www.bitmex.com/blog?tab=Product%20Updates"
        self._rss_cache = None  # Cache RSS data to avoid multiple fetches

    def _fetch_rss_data(self) -> ET.Element:
        """
        Fetch and cache RSS feed data.

        Returns:
            ElementTree root element
        """
        if self._rss_cache is None:
            response = self.session.get(self.rss_feed_url, timeout=15)
            response.raise_for_status()
            self._rss_cache = ET.fromstring(response.text)
        return self._rss_cache

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover product updates from RSS feed.

        Returns:
            Dict of update URL -> update title
        """
        self.logger.info(f"Fetching RSS feed from {self.rss_feed_url}...")

        sections = {}

        try:
            root = self._fetch_rss_data()

            # Extract all items (blog posts)
            for item in root.findall('.//item'):
                title_elem = item.find('title')
                link_elem = item.find('link')
                category_elems = item.findall('category')

                title = title_elem.text if title_elem is not None else 'No title'
                link = link_elem.text if link_elem is not None else ''
                categories = [cat.text for cat in category_elems if cat.text]

                # Check if this is a Product Update (API updates, new features, announcements)
                keywords = ['api', 'product', 'feature', 'launch', 'update', 'new listing', 'announcing', 'now live']
                is_product_related = (
                    any(keyword in title.lower() for keyword in keywords) or
                    any(keyword in ' '.join(categories).lower() for keyword in ['api', 'product', 'updates'])
                )

                if is_product_related and link:
                    sections[link] = title

            self.logger.info(f"  Found {len(sections)} product-related updates")

        except Exception as e:
            self.logger.error(f"  Error fetching RSS feed: {e}")

        return sections

    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Fetch a specific update's metadata and create a hash.

        Args:
            section_id: The update URL

        Returns:
            Tuple of (content representation, hash)
        """
        try:
            root = self._fetch_rss_data()

            # Find the specific item by URL
            for item in root.findall('.//item'):
                link_elem = item.find('link')
                if link_elem is not None and link_elem.text == section_id:
                    title_elem = item.find('title')
                    pubDate_elem = item.find('pubDate')
                    description_elem = item.find('description')
                    category_elems = item.findall('category')

                    title = title_elem.text if title_elem is not None else ''
                    pubDate = pubDate_elem.text if pubDate_elem is not None else ''
                    description = description_elem.text if description_elem is not None else ''
                    categories = [cat.text for cat in category_elems if cat.text]

                    # Create a content representation that includes key fields
                    content = f"{title}\n{pubDate}\n{section_id}\n{description}\n{','.join(categories)}"
                    content_hash = self.get_page_hash(content)

                    return content, content_hash

            # If not found, return empty
            return "", ""

        except Exception as e:
            self.logger.error(f"  Error fetching update details: {e}")
            return "", ""

    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific update.

        Args:
            section_id: The update URL

        Returns:
            The update URL
        """
        return section_id

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages with blog link.

        Returns:
            Footer string with blog link
        """
        return f"\n📚 Product Updates: [BitMEX Blog]({self.blog_url})"

    def print_summary_footer(self):
        """Print footer for summary with blog URL."""
        self.logger.info("View product updates at:")
        self.logger.info(f"  BitMEX Blog: {self.blog_url}")
        self.logger.info(f"  RSS Feed: {self.rss_feed_url}")


def main():
    """Main execution function."""
    # Create argument parser using base class helper
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="BitMEX", default_storage_file="state/bitmex_docs_state.json"
    )

    args = parser.parse_args()

    # Get Telegram credentials using base class helper
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor instance
    monitor = BitmexDocMonitor(
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
