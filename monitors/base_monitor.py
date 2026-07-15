#!/usr/bin/env python3
"""
Base Documentation Monitor Class

Provides common functionality for all exchange documentation monitors.
"""

import requests
from bs4 import BeautifulSoup
import hashlib
import json
import os
import re
from datetime import datetime
import time
from typing import Dict, Tuple
from abc import ABC, abstractmethod
from logger_config import setup_logger


class BaseDocMonitor(ABC):
    """Base class for documentation monitors with common functionality."""

    def __init__(
        self,
        exchange_name: str,
        storage_file: str,
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
            exchange_name: Name of the exchange (e.g., "Deribit", "Bybit", "Binance")
            storage_file: Path to JSON file storing previous state
            telegram_bot_token: Telegram bot token from @BotFather
            telegram_chat_id: Telegram chat ID to send messages to
            notify_additions: Send Telegram notification for new sections (default: True)
            notify_modifications: Send Telegram notification for modified sections (default: True)
            notify_deletions: Send Telegram notification for deleted sections (default: False)
            notify_no_sections: Send Telegram notification if exchange does not return any sections (default: True)
            notify_many_deletions: Send Telegram notification if many sections sections have been deleted (default: True)
            notify_many_deletions_threshold: Threshold for notify_many_deletions (default: 0.2 e.g. 20% of old sections)
        """

        self.exchange_name = exchange_name
        self.storage_file = storage_file
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.notify_additions = notify_additions
        self.notify_modifications = notify_modifications
        self.notify_deletions = notify_deletions
        self.notify_no_sections = notify_no_sections
        self.notify_many_deletions = notify_many_deletions
        self.notify_many_deletions_threshold = notify_many_deletions_threshold
        self.logger = setup_logger(exchange_name)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    def get_page_hash(self, content: str) -> str:
        """Generate SHA-256 hash of page content with whitespace normalization."""
        # Collapse all whitespace into single spaces
        normalized = re.sub(r"\s+", " ", content).strip()
        # Remove spaces around common punctuation
        normalized = re.sub(r"\s*([{}[\]:,])\s*", r"\1", normalized)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def load_previous_state(self) -> Dict:
        """Load previous state from storage file."""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading previous state: {e}")
        return {}

    def save_state(self, state: Dict):
        """Save current state to storage file."""
        try:
            with open(self.storage_file, "w") as f:
                json.dump(state, f, indent=2)
            self.logger.info(f"State saved to {self.storage_file}")
        except Exception as e:
            self.logger.error(f"Error saving state: {e}")

    @abstractmethod
    def discover_sections(self) -> Dict[str, str]:
        """
        Discover documentation sections/pages to monitor.

        Must be implemented by subclasses.

        Returns:
            Dict of section_id -> section_title
        """
        pass

    @abstractmethod
    def fetch_section_content(self, section_id: str) -> Tuple[str, str]:
        """
        Fetch a specific section's content and return its content and hash.

        Must be implemented by subclasses.

        Args:
            section_id: The section identifier

        Returns:
            Tuple of (content, hash)
        """
        pass

    @abstractmethod
    def get_section_url(self, section_id: str) -> str:
        """
        Get the URL for a specific section.

        Must be implemented by subclasses.

        Args:
            section_id: The section identifier

        Returns:
            Full URL to the section
        """
        pass

    def check_for_changes(self, save_content: bool = False) -> Dict:
        """
        Check all documentation sections for changes.

        Args:
            save_content: Whether to save full content (for detailed diffs)

        Returns:
            Dictionary with change information
        """
        self.logger.info("=" * 70)
        self.logger.info(f"{self.exchange_name} API Documentation Change Monitor")
        self.logger.info("=" * 70)

        # Discover sections
        sections = self.discover_sections()
        self.logger.info(f"Discovered {len(sections)} sections")

        if(len(sections) == 0 and self.notify_no_sections):
            try:
                url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                payload = {
                    "chat_id": self.telegram_chat_id,
                    "text": f"❌ Failed to find sections for {self.exchange_name}, this is likely indicative of a doc monitoring failure.",
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                }
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                self.logger.info("Telegram notification sent successfully")
            except Exception as e:
                self.logger.error(f"Failed to send Telegram notification: {e}")

        # Load previous state
        previous_state = self.load_previous_state()
        previous_sections = previous_state.get("sections", {})
        previous_timestamp = previous_state.get("timestamp", "Never")

        self.logger.info(f"Previous check: {previous_timestamp}")
        self.logger.info(f"Checking {len(sections)} sections for changes...")

        # Current state
        current_state = {"timestamp": datetime.now().isoformat(), "sections": {}}

        # Track changes
        changes = {
            "new_sections": [],
            "modified_sections": [],
            "deleted_sections": [],
            "unchanged_sections": [],
        }

        # Check each section
        for i, (section_id, section_title) in enumerate(sorted(sections.items()), 1):
            self.logger.info(f"[{i}/{len(sections)}] Checking {section_title}...")

            content, content_hash = self.fetch_section_content(section_id)

            if not content_hash:
                self.logger.warning(f"[{i}/{len(sections)}] {section_title}: FAILED")
                continue

            # Store in current state
            section_data = {
                "title": section_title,
                "hash": content_hash,
                "last_checked": datetime.now().isoformat(),
            }

            if save_content:
                section_data["content"] = content

            current_state["sections"][section_id] = section_data

            # Compare with previous state
            if section_id not in previous_sections:
                self.logger.info(f"[{i}/{len(sections)}] {section_title}: NEW")
                changes["new_sections"].append(
                    {"id": section_id, "title": section_title}
                )
            elif previous_sections[section_id].get("hash") != content_hash:
                self.logger.info(f"[{i}/{len(sections)}] {section_title}: MODIFIED")
                changes["modified_sections"].append(
                    {
                        "id": section_id,
                        "title": section_title,
                        "old_hash": previous_sections[section_id].get("hash"),
                        "new_hash": content_hash,
                    }
                )
            else:
                self.logger.debug(f"[{i}/{len(sections)}] {section_title}: UNCHANGED")
                changes["unchanged_sections"].append(section_id)

            time.sleep(0.3)  # Rate limiting

        # Check for deleted sections
        for section_id in previous_sections:
            if section_id not in current_state["sections"]:
                changes["deleted_sections"].append(
                    {
                        "id": section_id,
                        "title": previous_sections[section_id].get("title", "Unknown"),
                    }
                )

        if(len(changes["deleted_sections"]) > self.notify_many_deletions_threshold * len(previous_sections)and self.notify_many_deletions):
            try:
                url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                payload = {
                    "chat_id": self.telegram_chat_id,
                    "text": f"❌ {self.notify_many_deletions_threshold * 100}% or more of {self.exchange_name} sections have been deleted, this could be indicative of a doc monitoring failure.",
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                    }
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                self.logger.info("Telegram notification sent successfully")
            except Exception as e:
                self.logger.error(f"Failed to send Telegram notification: {e}")

        # Save current state
        self.save_state(current_state)

        return changes

    def get_section_label(self, section_id: str) -> str:
        """
        Get a label/prefix for a section (e.g., API type, category).

        Subclasses can override this to add custom labels.

        Args:
            section_id: The section identifier

        Returns:
            Label string (empty by default)
        """
        return ""

    def escape_markdown(self, text: str) -> str:
        """
        Escape Markdown special characters for Telegram.

        Args:
            text: Text to escape

        Returns:
            Escaped text safe for Telegram Markdown
        """
        # Escape underscores and other Markdown characters
        for char in ["_", "*", "`", "["]:
            text = text.replace(char, "\\" + char)
        return text

    def format_section_title(self, section: Dict) -> str:
        """
        Format a section title with optional label.

        Args:
            section: Section dictionary with 'id' and 'title'

        Returns:
            Formatted title string (Markdown-escaped)
        """
        label = self.get_section_label(section["id"])
        title = self.escape_markdown(section["title"])
        if label:
            return f"[{label}] {title}"
        return title

    def send_telegram(self, changes: Dict):
        """
        Send Telegram notification if changes were detected.

        Only sends notifications for change types that are enabled via
        notify_additions, notify_modifications, and notify_deletions settings.

        Args:
            changes: Dictionary with change information
        """
        # Count only changes we want to notify about
        notifiable_additions = len(changes["new_sections"]) if self.notify_additions else 0
        notifiable_modifications = len(changes["modified_sections"]) if self.notify_modifications else 0
        notifiable_deletions = len(changes["deleted_sections"]) if self.notify_deletions else 0
        total_notifiable = notifiable_additions + notifiable_modifications + notifiable_deletions

        if (
            total_notifiable == 0
            or not self.telegram_bot_token
            or not self.telegram_chat_id
        ):
            return

        # Build message
        message = f"🔔 *{self.exchange_name} API Documentation Changed*\n\n"
        message += f"📊 Total Changes: *{total_notifiable}*\n"
        message += f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n\n"

        if self.notify_additions and changes["new_sections"]:
            message += f"📄 *NEW SECTIONS ({len(changes['new_sections'])})*:\n"
            for section in changes["new_sections"][:10]:  # Limit to 10
                formatted_title = self.format_section_title(section)
                message += f"  • {formatted_title}\n"
                message += f"    [View]({section['id']})\n"
            if len(changes["new_sections"]) > 10:
                message += f"  ... and {len(changes['new_sections']) - 10} more\n"
            message += "\n"

        if self.notify_modifications and changes["modified_sections"]:
            message += f"✏️ *MODIFIED SECTIONS ({len(changes['modified_sections'])})*:\n"
            for section in changes["modified_sections"][:10]:  # Limit to 10
                formatted_title = self.format_section_title(section)
                message += f"  • {formatted_title}\n"
                message += f"    [View]({section['id']})\n"
            if len(changes["modified_sections"]) > 10:
                message += f"  ... and {len(changes['modified_sections']) - 10} more\n"
            message += "\n"

        if self.notify_deletions and changes["deleted_sections"]:
            message += f"🗑️ *DELETED SECTIONS ({len(changes['deleted_sections'])})*:\n"
            for section in changes["deleted_sections"][:10]:
                formatted_title = self.format_section_title(section)
                message += f"  • {formatted_title}\n"
            if len(changes["deleted_sections"]) > 10:
                message += f"  ... and {len(changes['deleted_sections']) - 10} more\n"

        # Add documentation link(s) - subclasses can override this
        message += self.get_telegram_footer()

        # Send via Telegram
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            self.logger.info("Telegram notification sent successfully")
        except Exception as e:
            self.logger.error(f"Failed to send Telegram notification: {e}")

    def get_telegram_footer(self) -> str:
        """
        Get the footer for Telegram messages.

        Can be overridden by subclasses for custom footers.

        Returns:
            Footer string
        """
        return ""

    def print_summary(self, changes: Dict):
        """Print a summary of changes."""
        self.logger.info("=" * 70)
        self.logger.info("CHANGE SUMMARY")
        self.logger.info("=" * 70)

        if changes["new_sections"]:
            self.logger.info(f"📄 NEW SECTIONS ({len(changes['new_sections'])}):")
            for section in changes["new_sections"]:
                formatted_title = self.format_section_title(section)
                self.logger.info(f"  + {formatted_title}")
                self.logger.info(f"    URL: {section['id']}")

        if changes["modified_sections"]:
            self.logger.info(
                f"✏️  MODIFIED SECTIONS ({len(changes['modified_sections'])}):"
            )
            for section in changes["modified_sections"]:
                formatted_title = self.format_section_title(section)
                self.logger.info(f"  ~ {formatted_title}")
                self.logger.info(f"    URL: {section['id']}")
                self.logger.info(f"    Old hash: {section['old_hash'][:16]}...")
                self.logger.info(f"    New hash: {section['new_hash'][:16]}...")

        if changes["deleted_sections"]:
            self.logger.info(
                f"🗑️  DELETED SECTIONS ({len(changes['deleted_sections'])}):"
            )
            for section in changes["deleted_sections"]:
                formatted_title = self.format_section_title(section)
                self.logger.info(f"  - {formatted_title}")
                self.logger.info(f"    URL: {section['id']}")

        self.logger.info(f"✓ UNCHANGED SECTIONS: {len(changes['unchanged_sections'])}")

        total_changes = (
            len(changes["new_sections"])
            + len(changes["modified_sections"])
            + len(changes["deleted_sections"])
        )

        if total_changes == 0:
            self.logger.info("✅ No changes detected!")
        else:
            self.logger.warning(f"⚠️  Total changes: {total_changes}")

        # Print documentation URLs - subclasses can override
        self.print_summary_footer()

    def print_summary_footer(self):
        """Print footer for summary. Can be overridden by subclasses."""
        pass

    @staticmethod
    def load_config_file(config_path: str) -> Dict:
        """
        Load configuration from JSON file.

        Args:
            config_path: Path to config file

        Returns:
            Configuration dictionary
        """
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                # Use print here since this is a static method without logger
                import sys

                print(f"Warning: Could not load config file: {e}", file=sys.stderr)
        return {}

    @staticmethod
    def create_argument_parser(exchange_name: str, default_storage_file: str):
        """
        Create a standard argument parser for exchange monitors.

        Args:
            exchange_name: Name of the exchange
            default_storage_file: Default storage file name

        Returns:
            ArgumentParser instance
        """
        import argparse

        parser = argparse.ArgumentParser(
            description=f"Monitor {exchange_name} API documentation for changes with Telegram notifications"
        )
        parser.add_argument(
            "--storage-file",
            default=default_storage_file,
            help=f"Path to state storage file (default: {default_storage_file})",
        )
        parser.add_argument(
            "--save-content",
            action="store_true",
            help="Save full section content for detailed diffs (increases storage)",
        )
        parser.add_argument(
            "--config",
            default="config.json",
            help="Path to config file with Telegram credentials (default: config.json)",
        )
        parser.add_argument(
            "--telegram-token",
            help="Telegram bot token from @BotFather (overrides config file)",
        )
        parser.add_argument(
            "--telegram-chat-id",
            help="Telegram chat ID to send notifications to (overrides config file)",
        )
        parser.add_argument(
            "--no-telegram", action="store_true", help="Disable Telegram notifications"
        )
        parser.add_argument(
            "--notify-additions",
            action="store_true",
            dest="notify_additions",
            default=None,
            help="Enable Telegram notifications for new sections (default: enabled)",
        )
        parser.add_argument(
            "--no-notify-additions",
            action="store_false",
            dest="notify_additions",
            help="Disable Telegram notifications for new sections",
        )
        parser.add_argument(
            "--notify-modifications",
            action="store_true",
            dest="notify_modifications",
            default=None,
            help="Enable Telegram notifications for modified sections (default: enabled)",
        )
        parser.add_argument(
            "--no-notify-modifications",
            action="store_false",
            dest="notify_modifications",
            help="Disable Telegram notifications for modified sections",
        )
        parser.add_argument(
            "--notify-deletions",
            action="store_true",
            dest="notify_deletions",
            default=None,
            help="Enable Telegram notifications for deleted sections (default: disabled)",
        )
        parser.add_argument(
            "--no-notify-deletions",
            action="store_false",
            dest="notify_deletions",
            help="Disable Telegram notifications for deleted sections",
        )

        return parser

    @staticmethod
    def get_telegram_credentials(args):
        """
        Get Telegram credentials from arguments and config file.

        Args:
            args: Parsed command-line arguments

        Returns:
            Tuple of (telegram_token, telegram_chat_id)
        """
        telegram_token = args.telegram_token
        telegram_chat_id = args.telegram_chat_id

        if not args.no_telegram and os.path.exists(args.config):
            config = BaseDocMonitor.load_config_file(args.config)
            if not telegram_token:
                telegram_token = config.get("telegram", {}).get("bot_token")
            if not telegram_chat_id:
                telegram_chat_id = config.get("telegram", {}).get("chat_id")

        # Disable if no-telegram flag set
        if args.no_telegram:
            telegram_token = None
            telegram_chat_id = None

        return telegram_token, telegram_chat_id

    @staticmethod
    def get_notification_settings(args):
        """
        Get notification settings from arguments and config file.

        Priority: CLI args > config file > defaults
        Defaults: additions=True, modifications=True, deletions=False

        Args:
            args: Parsed command-line arguments

        Returns:
            Tuple of (notify_additions, notify_modifications, notify_deletions)
        """
        # Load config file settings if available
        config_additions = None
        config_modifications = None
        config_deletions = None
        config_no_sections = None


        if os.path.exists(args.config):
            config = BaseDocMonitor.load_config_file(args.config)
            notifications = config.get("notifications", {})
            config_additions = notifications.get("additions")
            config_modifications = notifications.get("modifications")
            config_deletions = notifications.get("deletions")
            config_no_sections = notifications.get("no_sections")
            config_many_deletions = notifications.get("many_deletions")
            config_many_deletions_threshold = notifications.get("many_deletions_threshold")


        # CLI args override config, config overrides defaults
        # Default: additions=True, modifications=True, deletions=False, no_sections=True
        notify_additions = (
            args.notify_additions
            if args.notify_additions is not None
            else (config_additions if config_additions is not None else True)
        )
        notify_modifications = (
            args.notify_modifications
            if args.notify_modifications is not None
            else (config_modifications if config_modifications is not None else True)
        )
        notify_deletions = (
            args.notify_deletions
            if args.notify_deletions is not None
            else (config_deletions if config_deletions is not None else False)
        )
        notify_no_sections = (
            args.notify_no_sections
            if args.notify_no_sections is not None
            else (config_no_sections if config_no_sections is not None else True)
        )
        notify_many_deletions = (
            args.notify_many_deletions
            if args.notify_many_deletions is not None
            else (config_many_deletions if config_many_deletions is not None else True)
        )
        notify_many_deletions_threshold = (
            args.notify_many_deletions_threshold
            if args.notify_many_deletions_threshold is not None
            else (config_many_deletions_threshold if config_many_deletions_threshold is not None else 0.2)
        )

        return notify_additions, notify_modifications, notify_deletions, notify_no_sections, notify_many_deletions, notify_many_deletions_threshold
