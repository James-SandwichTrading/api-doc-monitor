#!/usr/bin/env python3
"""
Base class for documentation monitors that need a browser to render pages.

Pages are rendered with headless Chrome via Selenium. One browser is shared by
every page in a run and closed when the run ends.

Rendering is retried, and a run whose browser is clearly broken stops rendering
early instead of retrying every remaining page:
- Each page gets BROWSER_MAX_RENDER_ATTEMPTS attempts, with a fresh browser
  after a failure.
- If the browser itself cannot be started, rendering stops for the run.
- If BROWSER_MAX_CONSECUTIVE_PAGE_FAILURES pages in a row fail every attempt,
  rendering stops for the run.
Pages that were not rendered are reported on Telegram once at the end of the run.
"""

import time
from abc import abstractmethod
from typing import List
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from .base_monitor import BaseDocMonitor


class BrowserStartError(Exception):
    """The browser could not be started, so no page can be rendered."""


class SeleniumDocMonitor(BaseDocMonitor):
    """Base class for monitors whose pages are rendered with Selenium."""

    # Times a page is attempted before it is reported as failed
    BROWSER_MAX_RENDER_ATTEMPTS = 3

    # Seconds to wait between attempts at rendering a page
    BROWSER_RETRY_DELAY = 5

    # Pages in a row that may fail every attempt before rendering stops for the run
    BROWSER_MAX_CONSECUTIVE_PAGE_FAILURES = 3

    # Failed pages listed in the Telegram warning before "... and N more"
    BROWSER_MAX_PAGES_IN_WARNING = BaseDocMonitor.TELEGRAM_MAX_SECTIONS_PER_GROUP

    def __init__(self, *args, **kwargs):
        """Initialize the monitor. Takes the same arguments as BaseDocMonitor."""
        super().__init__(*args, **kwargs)

        # Rendered HTML for each URL fetched this run
        self._page_cache = {}

        # Browser shared by every page in a run, created on first use
        self._driver = None

        # Pages that were not rendered this run, in the order they were requested
        self._failed_pages: List[str] = []

        # Why rendering stopped for the run, or None while it is still running
        self._render_stopped_reason = None

        # Pages in a row that failed every attempt
        self._consecutive_page_failures = 0

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

    def _render_page(self, url: str) -> str:
        """
        Render a page once in the shared browser, raising if anything goes wrong.

        Args:
            url: The URL to fetch

        Returns:
            Rendered HTML content

        Raises:
            BrowserStartError: The browser could not be started
            Exception: The page could not be loaded or did not become ready
        """
        if not self._driver:
            try:
                self._driver = self._create_driver()
            except Exception as e:
                raise BrowserStartError(f"{type(e).__name__}: {e}") from e

        self._driver.get(url)
        self._wait_for_page(self._driver)
        return self._driver.page_source

    def _fetch_rendered_page(self, url: str) -> str:
        """
        Fetch a page using Selenium to render JavaScript content.

        Args:
            url: The URL to fetch

        Returns:
            Rendered HTML content, or "" if the page was not rendered
        """
        if url in self._page_cache:
            return self._page_cache[url]
        if url in self._failed_pages:
            return ""
        if self._render_stopped_reason:
            self._failed_pages.append(url)
            return ""

        self.logger.info(f"  Rendering page with Selenium: {url}")
        attempts = self.BROWSER_MAX_RENDER_ATTEMPTS
        browser_failed = False
        for attempt in range(1, attempts + 1):
            try:
                html = self._render_page(url)
                self._page_cache[url] = html
                self._consecutive_page_failures = 0
                return html

            except Exception as e:
                browser_failed = isinstance(e, BrowserStartError)

                # Start a fresh browser for the next attempt in case this one is broken
                self._close_driver()

                # Selenium timeouts carry no message, so always name the exception
                error = f"{type(e).__name__}: {e}"
                if attempt == attempts:
                    self.logger.error(f"  Error rendering page {url}: {error}")
                    break
                self.logger.warning(
                    f"  Attempt {attempt}/{attempts} failed rendering {url}: {error.splitlines()[0]}"
                )
                time.sleep(self.BROWSER_RETRY_DELAY)

        self._failed_pages.append(url)

        if browser_failed:
            # Nothing page-specific about this: no page can be rendered this run
            self._stop_rendering("the browser could not be started")
        else:
            self._consecutive_page_failures += 1
            if self._consecutive_page_failures >= self.BROWSER_MAX_CONSECUTIVE_PAGE_FAILURES:
                self._stop_rendering(
                    f"{self._consecutive_page_failures} pages in a row failed to render"
                )

        return ""

    def _stop_rendering(self, reason: str):
        """Give up on rendering for the rest of the run."""
        self._render_stopped_reason = reason
        self.logger.error(f"  Stopped rendering pages for this run: {reason}")

    def _send_render_failure_warning(self):
        """Warn on Telegram about pages that were not rendered this run."""
        if not self._failed_pages:
            return
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return

        count = len(self._failed_pages)
        text = (
            f"❌ Failed to render {count} {self.exchange_name} documentation "
            f"page{'s' if count != 1 else ''}, this is likely indicative of a doc "
            "monitoring failure."
        )
        if self._render_stopped_reason:
            text += f" Rendering stopped for this run because {self._render_stopped_reason}."
        text += " These pages were not fetched this run:\n"

        listed = self._failed_pages[: self.BROWSER_MAX_PAGES_IN_WARNING]
        for page_url in listed:
            text += f"  • {self.escape_markdown(page_url)}\n"
        if count > len(listed):
            text += f"  ... and {count - len(listed)} more\n"

        self._send_telegram_messages(
            self.telegram_chat_id, [text.rstrip()], "render failure warning"
        )

    def check_for_changes(self, *args, **kwargs):
        """Check for changes, warning about unrendered pages and closing the browser afterwards."""
        try:
            changes = super().check_for_changes(*args, **kwargs)
        finally:
            self._close_driver()
        self._send_render_failure_warning()
        return changes
