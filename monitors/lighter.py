#!/usr/bin/env python3
"""
Lighter API Documentation Change Monitor with Telegram Notifications

This script monitors Lighter API documentation (API Reference) and tracks changes
by storing page hashes for comparison.

Automatically sends Telegram notifications when changes are detected.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from .base_monitor import BaseDocMonitor
from .selenium_monitor import SeleniumDocMonitor


class LighterDocMonitor(SeleniumDocMonitor):
    """Monitor for Lighter API documentation hosted on GitBook."""

    BASE_URL = "https://docs.lighter.xyz"

    # Seed pages to scrape sidebar navigation from
    SEED_PAGES = {
        "reference": f"{BASE_URL}/api",
    }

    def __init__(
        self,
        storage_file: str = "state/lighter_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        telegram_admin_chat_id: str = None,
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
            telegram_admin_chat_id: Chat ID that receives the full list when a notification is cut off (optional)
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """
        super().__init__(
            exchange_name="Lighter",
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

        # Pattern to match "Updated\nX days/weeks/months/years ago" text
        # This avoids false positives from relative timestamp changes
        self._updated_pattern = re.compile(
            r"Updated\n(\s*about)?\s*\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago(?:\nDid this page help you\?\nYes\nNo)?",
            re.IGNORECASE,
        )

    def get_page_hash(self, content: str) -> str:
        """
        Hash page content with all whitespace removed.

        GitBook highlights code in the browser after the page loads, which splits
        code into tokens (e.g. "HTTP/1.1" becomes "HTTP / 1.1"). Ignoring whitespace
        makes the hash the same whether or not highlighting has finished.
        """
        return super().get_page_hash(re.sub(r"\s+", "", content))

    def _wait_for_page(self, driver):
        """
        Wait for the page body and expand every collapsed schema.

        GitBook builds code samples in the browser and only loads schema properties
        (e.g. on /api/models) when their "Show properties" toggle is clicked, so
        every toggle on the page is clicked before the HTML is read.
        """
        # Wait for page content to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "main"))
        )

        # Expand every collapsed schema so its properties are rendered
        toggles = driver.find_elements(
            By.XPATH, "//main//*[normalize-space(text())='Show properties']"
        )
        for toggle in toggles:
            driver.execute_script("arguments[0].click();", toggle)

    def _discover_sidebar_links(self, seed_url: str, prefix: str) -> Dict[str, str]:
        """
        Fetch a seed page and extract all sidebar navigation links matching a prefix.

        Args:
            seed_url: URL to fetch for sidebar discovery
            prefix: URL path prefix to filter links (e.g., "/api")

        Returns:
            Dict of full_url -> page_title
        """
        pages = {}

        try:
            html = self._fetch_rendered_page(seed_url)
            if not html:
                return pages

            soup = BeautifulSoup(html, "html.parser")

            # GitBook sidebar links are <a> tags with hrefs starting with the prefix
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")

                # Match links like /api or /api/system/status
                if not href.startswith(prefix):
                    continue

                # Skip in-page anchors (e.g. /api/websocket#trade), the page itself is already tracked
                if "#" in href:
                    continue

                # Endpoint links carry an HTTP method badge, e.g. "get" + "status"
                method = link.find(class_="openapi-method")
                method_text = ""
                if method:
                    method_text = method.get_text(strip=True).upper()
                    method.decompose()

                title = link.get_text(strip=True)

                # Skip empty titles, overly long ones, or pure navigation elements
                if not title or len(title) > 150:
                    continue

                if method_text:
                    title = f"{method_text} {title}"

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

        GitBook only expands a sidebar group on that group's own pages, so every
        discovered page is visited to reveal its children.

        Returns:
            Dict of page_url -> page_title
        """
        all_sections = {}

        self.logger.info(
            f"Discovering reference pages from {self.SEED_PAGES['reference']}..."
        )
        to_visit = [self.SEED_PAGES["reference"]]
        visited = set()

        while to_visit:
            page_url = to_visit.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)

            for url, title in self._discover_sidebar_links(page_url, "/api").items():
                if url not in all_sections:
                    all_sections[url] = title
                    to_visit.append(url)

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
            html = self._fetch_rendered_page(page_url)
            if not html:
                return "", ""

            soup = BeautifulSoup(html, "html.parser")

            # Remove non-content elements
            for element in soup(
                ["script", "style", "nav", "footer", "header", "aside"]
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
        if "/api" in section_id:
            return "API"
        return ""

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages with documentation links.

        Returns:
            Footer string with documentation links
        """
        message = "\n📚 Documentation:\n"
        message += f"  • [API Reference]({self.SEED_PAGES['reference']})"
        return message

    def print_summary_footer(self):
        """Print footer for summary with documentation URLs."""
        self.logger.info("View documentation at:")
        self.logger.info(f"  API Reference: {self.SEED_PAGES['reference']}")


def main():
    """Main execution function."""
    # Create argument parser using base class helper
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Lighter",
        default_storage_file="state/lighter_docs_state.json",
    )

    args = parser.parse_args()

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
        telegram_admin_chat_id=BaseDocMonitor.get_telegram_admin_chat_id(args),
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
