#!/usr/bin/env python3
"""
Base class for documentation monitors that need a browser to render pages.

Pages are rendered with headless Chrome via Selenium. One browser is shared by
every page in a run and closed when the run ends.
"""

from abc import abstractmethod
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from .base_monitor import BaseDocMonitor


class SeleniumDocMonitor(BaseDocMonitor):
    """Base class for monitors whose pages are rendered with Selenium."""

    def __init__(self, *args, **kwargs):
        """Initialize the monitor. Takes the same arguments as BaseDocMonitor."""
        super().__init__(*args, **kwargs)

        # Rendered HTML for each URL fetched this run
        self._page_cache = {}

        # Browser shared by every page in a run, created on first use
        self._driver = None

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

    def _close_driver(self):
        """Close the shared browser if one is open."""
        if self._driver:
            try:
                self._driver.quit()
            except Exception as e:
                self.logger.warning(f"  Error closing browser: {e}")
            self._driver = None

    @abstractmethod
    def _wait_for_page(self, driver):
        """
        Wait until a freshly loaded page is ready to be read.

        Each exchange waits for its own content and may interact with the page
        (e.g. expanding collapsed sections) before the HTML is captured.

        Args:
            driver: WebDriver that has just loaded the page
        """
        pass

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

        try:
            self.logger.info(f"  Rendering page with Selenium: {url}")
            if not self._driver:
                self._driver = self._create_driver()
            self._driver.get(url)

            self._wait_for_page(self._driver)

            html = self._driver.page_source
            self._page_cache[url] = html
            return html

        except Exception as e:
            self.logger.error(f"  Error rendering page {url}: {e}")
            # Start a fresh browser for the next page in case this one is broken
            self._close_driver()
            return ""

    def check_for_changes(self, *args, **kwargs):
        """Check for changes, closing the shared browser afterwards."""
        try:
            return super().check_for_changes(*args, **kwargs)
        finally:
            self._close_driver()
