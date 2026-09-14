#!/usr/bin/env python3
"""
HTX API Documentation Change Monitor with Telegram Notifications

This script monitors the HTX (formerly Huobi) API update record and tracks
changes by storing section hashes for comparison.

HTX's API documentation portal (https://www.htx.com/en-us/opend/newApiPages/)
is a JavaScript app, but its "Updates" page is fed by a JSON endpoint that
lists every API change with its date, endpoint, business line, update type and
summary. Each record is tracked as its own section, limited to the current and
previous year (like the other changelog monitors) so new records show up as
additions.

Automatically sends Telegram notifications when changes are detected.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .base_monitor import BaseDocMonitor


class HTXDocMonitor(BaseDocMonitor):
    """Monitor for the HTX API update record."""

    UPDATE_RECORD_API = "https://www.htx.com/oplt/api/open_api/update_record"
    UPDATE_RECORD_PAGE = "https://www.htx.com/en-us/opend/newApiPages/?id=record"
    DOCS_URL = "https://www.htx.com/en-us/opend/newApiPages/"

    # The API returns everything in one page when asked for a large page size
    PAGE_SIZE = 10000

    # Some business line names come back untranslated
    BIZ_TYPE_TRANSLATIONS = {"通用": "General"}

    # Summaries are truncated to this length in section titles
    MAX_TITLE_SUMMARY_LENGTH = 100

    def __init__(
        self,
        storage_file: str = "state/htx_docs_state.json",
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
        Initialize the HTX documentation monitor.

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
            exchange_name="HTX",
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

        # Get current year and previous year for filtering
        current_year = datetime.now().year
        self.years_to_monitor = [current_year, current_year - 1]

        # Without this the API answers in Chinese
        self.session.headers.update({"Accept-Language": "en-US,en;q=0.9"})

        # Record content keyed by section id (filled during discovery)
        self._record_content_cache: Dict[str, str] = {}

    def _cutoff_date(self) -> str:
        """
        Get the earliest update date to monitor as YYYY-MM-DD: 1 January of the
        earliest monitored year.

        Returns:
            Cutoff date string (comparable with the API's update_time values)
        """
        return f"{min(self.years_to_monitor):04d}-01-01"

    def _fetch_update_records(self) -> Optional[List[Dict]]:
        """
        Fetch all update records from the API.

        Returns:
            List of record dictionaries, or None if the request failed
        """
        try:
            response = self.session.get(
                self.UPDATE_RECORD_API,
                params={"pageNum": 1, "pageSize": self.PAGE_SIZE, "searchInfo": ""},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            records = data.get("list")
            if records is None:
                self.logger.error(f"  Unexpected update record response: {str(payload)[:200]}")
                return None
            total = data.get("total")
            if total is not None and total > len(records):
                self.logger.warning(
                    f"  Update record API returned {len(records)} of {total} records"
                )
            return records
        except Exception as e:
            self.logger.error(f"  Error fetching update records: {e}")
            return None

    def _biz_type(self, record: Dict) -> str:
        """Get the record's business line name, translated where needed."""
        biz_type = (record.get("biz_type") or "").strip()
        return self.BIZ_TYPE_TRANSLATIONS.get(biz_type, biz_type)

    def _record_title(self, record: Dict) -> str:
        """
        Build the section title for a record, e.g.
        "2026-08-17 [General] /v5/trade/order (Add): A cancel_volume field has been added..."

        Args:
            record: Update record from the API

        Returns:
            Title string
        """
        summary = " ".join((record.get("update_summary") or "").split())
        if len(summary) > self.MAX_TITLE_SUMMARY_LENGTH:
            summary = summary[: self.MAX_TITLE_SUMMARY_LENGTH - 3].rstrip() + "..."

        title = f"{record.get('update_time', '')} [{self._biz_type(record)}] "
        title += f"{(record.get('interface_path') or '').strip()} ({record.get('update_type', '')})"
        if summary:
            title += f": {summary}"
        return title

    def _record_content(self, record: Dict) -> str:
        """
        Build the content used for change detection of a record.

        Args:
            record: Update record from the API

        Returns:
            Content string
        """
        return "\n".join(
            [
                f"Date: {record.get('update_time', '')}",
                f"Interface: {(record.get('interface_path') or '').strip()}",
                f"Business: {self._biz_type(record)}",
                f"Type: {record.get('update_type', '')}",
                f"Summary: {' '.join((record.get('update_summary') or '').split())}",
            ]
        )

    def discover_sections(self) -> Dict[str, str]:
        """
        Discover recent update records.

        Records have no id of their own, so the section id is built from the
        date, interface id and update type, with a counter appended when the
        same interface has several records of the same type on one day.

        Returns:
            Dict of section_id -> title
        """
        sections = {}
        cutoff = self._cutoff_date()
        self.logger.info(
            f"Fetching update records from {self.UPDATE_RECORD_API} (from {cutoff} onwards)..."
        )

        records = self._fetch_update_records()
        if records is None:
            return sections

        skipped = 0
        occurrences: Dict[str, int] = {}
        for record in records:
            update_time = record.get("update_time") or ""
            if update_time < cutoff:
                skipped += 1
                continue

            base_key = f"{update_time}-{record.get('interface_id', '')}-{record.get('update_type_code', '')}"
            occurrences[base_key] = occurrences.get(base_key, 0) + 1
            fragment = base_key
            if occurrences[base_key] > 1:
                fragment += f"-{occurrences[base_key]}"

            section_id = f"{self.UPDATE_RECORD_PAGE}#{fragment}"
            sections[section_id] = self._record_title(record)
            self._record_content_cache[section_id] = self._record_content(record)
            self.logger.debug(f"  Found update record: {sections[section_id]}")

        self.logger.info(
            f"Discovered {len(sections)} recent update records"
            + (f" ({skipped} older records skipped)" if skipped else "")
        )

        return sections

    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Get a record's content and hash from the discovery cache.

        Args:
            section_id: The section identifier

        Returns:
            Tuple of (content, hash)
        """
        content = self._record_content_cache.get(section_id, "")
        if not content:
            self.logger.warning(f"  No content cached for section: {section_id}")
            return "", ""
        return content, self.get_page_hash(content)

    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific section.

        Args:
            section_id: The section identifier

        Returns:
            The URL (same as section_id)
        """
        return section_id

    def get_telegram_footer(self) -> str:
        """Get the footer for Telegram messages with documentation links."""
        return (
            f"\n📚 Documentation: [HTX API Docs]({self.DOCS_URL})"
            f"\n📝 Update record: [HTX API Update Record]({self.UPDATE_RECORD_PAGE})"
        )

    def print_summary_footer(self):
        """Print footer for summary with documentation URLs."""
        self.logger.info("View documentation at:")
        self.logger.info(f"  HTX API docs: {self.DOCS_URL}")
        self.logger.info(f"  HTX update record: {self.UPDATE_RECORD_PAGE}")


def main():
    """Main execution function."""
    parser = BaseDocMonitor.create_argument_parser(
        exchange_name="HTX", default_storage_file="state/htx_docs_state.json"
    )
    args = parser.parse_args()

    # Get Telegram credentials
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(args)

    # Get notification settings
    (
        notify_additions,
        notify_modifications,
        notify_deletions,
        notify_no_sections,
        notify_many_deletions,
        notify_many_deletions_threshold,
    ) = BaseDocMonitor.get_notification_settings(args)

    # Create monitor instance
    monitor = HTXDocMonitor(
        storage_file=args.storage_file,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        notify_additions=notify_additions,
        notify_modifications=notify_modifications,
        notify_deletions=notify_deletions,
        notify_no_sections=notify_no_sections,
        notify_many_deletions=notify_many_deletions,
        notify_many_deletions_threshold=notify_many_deletions_threshold,
    )

    # Check for changes
    changes = monitor.check_for_changes(save_content=args.save_content)

    # Print summary
    monitor.print_summary(changes)

    # Send Telegram notification if changes detected
    monitor.send_telegram(changes)


if __name__ == "__main__":
    main()
