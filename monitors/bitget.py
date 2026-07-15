#!/usr/bin/env python3
"""
Bitget API Documentation Change Monitor with Telegram Notifications

This script monitors Bitget API changelog documentation and tracks changes
by storing section hashes for comparison.

Uses Selenium to render JavaScript-heavy pages.
Automatically sends Telegram notifications when changes are detected.
"""

from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Tuple
import re
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from .base_monitor import BaseDocMonitor


class BitgetDocMonitor(BaseDocMonitor):
    def __init__(
        self,
        storage_file: str = "state/bitget_docs_state.json",
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        monitor_classic: bool = True,
        monitor_uta: bool = True,
        notify_additions: bool = True,
        notify_modifications: bool = True,
        notify_deletions: bool = False,
        notify_no_sections: bool = True,
        notify_many_deletions: bool = True,
        notify_many_deletions_threshold: float = 0.2,
    ):
        """
        Initialize the Bitget documentation monitor.

        Args:
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            monitor_classic: Whether to monitor Classic Account changelog
            monitor_uta: Whether to monitor UTA (Unified Trading Account) changelog
            notify_additions: Send Telegram notification for new sections
            notify_modifications: Send Telegram notification for modified sections
            notify_deletions: Send Telegram notification for deleted sections
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """
        super().__init__(
            exchange_name="Bitget",
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

        self.urls = {}
        if monitor_classic:
            self.urls["classic"] = "https://www.bitget.com/api-doc/common/changelog"
        if monitor_uta:
            self.urls["uta"] = "https://www.bitget.com/api-doc/uta/changelog"

        # Get current year and previous year for filtering
        current_year = datetime.now().year
        self.years_to_monitor = [current_year, current_year - 1]

        # Month names for pattern matching
        self.months = [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december"
        ]

        # Cache for rendered page content
        self._page_cache = {}

    def _create_driver(self):
        """Create a headless Chrome WebDriver."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver

    def _fetch_rendered_page(self, url: str) -> str:
        """
        Fetch a page using Selenium to render JavaScript content.

        Args:
            url: The URL to fetch

        Returns:
            Rendered HTML content
        """
        if url in self._page_cache:
            return self._page_cache[url]

        driver = None
        try:
            self.logger.info(f"  Rendering page with Selenium: {url}")
            driver = self._create_driver()
            driver.get(url)

            # Wait for changelog content to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h2[id], h3[id], [id*='20']"))
            )

            # Additional wait for dynamic content
            time.sleep(2)

            html = driver.page_source
            self._page_cache[url] = html
            return html

        except Exception as e:
            self.logger.error(f"  Error rendering page {url}: {e}")
            return ""
        finally:
            if driver:
                driver.quit()

    def _is_recent_section(self, section_id: str) -> bool:
        """
        Check if a section ID represents a recent update (current or previous year).

        Section IDs follow the pattern: month-day-year-title
        e.g., january-7-2026-optimization-of-push-frequency...

        Args:
            section_id: The section ID to check

        Returns:
            True if section is from current or previous year
        """
        # Pattern: month-day-year at the start of the ID
        pattern = r"^([a-z]+)-(\d+)-(\d{4})-"
        match = re.match(pattern, section_id.lower())

        if match:
            year = int(match.group(3))
            return year in self.years_to_monitor

        # Also check for year anywhere in the ID
        years_found = re.findall(r"\b(20\d{2})\b", section_id)
        if years_found:
            for year_str in years_found:
                if int(year_str) in self.years_to_monitor:
                    return True
            return False

        # If no year pattern found, include it
        return True

    def _extract_section_title(self, section_id: str) -> str:
        """
        Extract a readable title from the section ID.

        Args:
            section_id: The section ID (e.g., january-7-2026-optimization-of...)

        Returns:
            Formatted title string
        """
        # Pattern: month-day-year-title
        pattern = r"^([a-z]+)-(\d+)-(\d{4})-(.+)$"
        match = re.match(pattern, section_id.lower())

        if match:
            month = match.group(1).capitalize()
            day = match.group(2)
            year = match.group(3)
            title_slug = match.group(4)

            # Convert slug to title
            title = title_slug.replace("-", " ").title()

            # Truncate if too long
            if len(title) > 60:
                title = title[:57] + "..."

            return f"{month} {day}, {year}: {title}"

        # Fallback: just clean up the ID
        return section_id.replace("-", " ").title()

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover changelog sections from Bitget documentation pages.
        Only includes sections from current and previous year.

        Returns:
            Dict of url -> section_title
        """
        all_sections = {}
        filtered_count = 0

        for api_type, url in self.urls.items():
            self.logger.info(f"Fetching {api_type.upper()} changelog from {url}...")
            self.logger.info(
                f"  Filtering for years: {', '.join(map(str, self.years_to_monitor))}"
            )

            try:
                html = self._fetch_rendered_page(url)
                if not html:
                    continue

                soup = BeautifulSoup(html, "html.parser")

                # Find all elements with IDs that look like changelog entries
                # Pattern: month-day-year-description
                for element in soup.find_all(id=True):
                    section_id = element.get("id", "")

                    # Check if ID matches the changelog pattern (month-day-year-)
                    if any(section_id.lower().startswith(f"{month}-") for month in self.months):
                        if self._is_recent_section(section_id):
                            full_url = f"{url}#{section_id}"
                            section_title = self._extract_section_title(section_id)
                            all_sections[full_url] = section_title
                            self.logger.debug(f"  Found section: {section_title}")
                        else:
                            filtered_count += 1
                            self.logger.debug(f"  Filtered old section: {section_id}")

                section_count = len([k for k in all_sections if k.startswith(url)])
                self.logger.info(f"  Discovered {section_count} sections for {api_type}")
                if filtered_count > 0:
                    self.logger.info(f"  Filtered out {filtered_count} older sections")

            except Exception as e:
                self.logger.error(f"  Error fetching {api_type} changelog: {e}")

        return all_sections

    def fetch_section_content(self, section_url: str) -> Tuple[str, str]:
        """
        Fetch a specific section's content and return its content and hash.

        Args:
            section_url: The full section URL (with fragment)

        Returns:
            Tuple of (content, hash)
        """
        if "#" not in section_url:
            return "", ""

        section_id = section_url.split("#")[-1]
        base_url = section_url.split("#")[0]

        try:
            # Use cached page if available
            html = self._page_cache.get(base_url) or self._fetch_rendered_page(base_url)
            if not html:
                return "", ""

            soup = BeautifulSoup(html, "html.parser")

            # Find the section by ID
            section = soup.find(id=section_id)
            if not section:
                self.logger.warning(f"  Section not found: {section_id}")
                return "", ""

            # Get the section element and its following content
            content_parts = []

            # Get the heading/title text
            content_parts.append(section.get_text(strip=True))

            # Get following sibling content until next changelog entry
            for sibling in section.find_next_siblings():
                # Check if this is another changelog entry (starts with month name)
                sibling_id = sibling.get("id", "")
                if any(sibling_id.lower().startswith(f"{month}-") for month in self.months):
                    break

                # Skip navigation/script elements
                if sibling.name in ["script", "style", "nav", "footer", "header"]:
                    continue

                text = sibling.get_text(separator=" ", strip=True)
                if text:
                    content_parts.append(text)

            content = "\n".join(content_parts)
            content_hash = self.get_page_hash(content)

            return content, content_hash

        except Exception as e:
            self.logger.error(f"  Error fetching section {section_url}: {e}")
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
        Get the footer for Telegram messages with documentation links.

        Returns:
            Footer string with documentation links
        """
        message = "\n📚 Documentation:\n"
        if "classic" in self.urls:
            message += f"  • [Classic API Changelog]({self.urls['classic']})\n"
        if "uta" in self.urls:
            message += f"  • [UTA Changelog]({self.urls['uta']})"
        return message

    def get_section_label(self, section_id: str) -> str:
        """Get API type label from URL."""
        for api_type, api_url in self.urls.items():
            if section_id.startswith(api_url):
                return api_type.upper()
        return ""

    def print_summary_footer(self):
        """Print footer for summary with documentation URLs."""
        self.logger.info("View documentation at:")
        for api_type, url in self.urls.items():
            self.logger.info(f"  {api_type.upper()}: {url}")


def main():
    """Main execution function."""
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="Bitget", default_storage_file="state/bitget_docs_state.json"
    )

    # Add Bitget-specific arguments
    parser.add_argument(
        "--classic-only",
        action="store_true",
        help="Monitor only Classic Account changelog",
    )
    parser.add_argument(
        "--uta-only",
        action="store_true",
        help="Monitor only UTA (Unified Trading Account) changelog",
    )

    args = parser.parse_args()

    # Determine which APIs to monitor
    monitor_classic = not args.uta_only
    monitor_uta = not args.classic_only

    # Get Telegram credentials
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions = (
        BaseDocMonitor.get_notification_settings(args)
    )

    # Create monitor instance
    monitor = BitgetDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        monitor_classic=monitor_classic,
        monitor_uta=monitor_uta,
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
