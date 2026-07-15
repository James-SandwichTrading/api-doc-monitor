#!/usr/bin/env python3
"""
Master script to run all exchange documentation monitors.

This script runs all configured exchange monitors sequentially and collects
results. Useful for cron jobs or scheduled monitoring.
"""

import argparse
import sys
from datetime import datetime
from monitors import (
    BinanceDocMonitor,
    BitgetDocMonitor,
    BitmexDocMonitor,
    BybitDocMonitor,
    CoinbaseDocMonitor,
    DeribitDocMonitor,
    HyperliquidDocMonitor,
    KrakenDocMonitor,
    LighterDocMonitor,
    OKXDocMonitor,
    BaseDocMonitor,
)
from logger_config import setup_logger


def run_monitor(monitor_class, monitor_name, logger, save_content=True, **kwargs):
    """
    Run a single monitor and return results.

    Args:
        monitor_class: The monitor class to instantiate
        monitor_name: Human-readable name for logging
        logger: Logger instance for run_all
        save_content: Whether to save full content for diffs
        **kwargs: Additional arguments to pass to the monitor

    Returns:
        Dict with change information
    """
    logger.info("=" * 80)
    logger.info(f"Running {monitor_name} Monitor")
    logger.info("=" * 80)

    try:
        monitor = monitor_class(**kwargs)
        changes = monitor.check_for_changes(save_content=save_content)
        monitor.print_summary(changes)
        monitor.send_telegram(changes)

        return {
            "success": True,
            "monitor": monitor_name,
            "changes": changes,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error running {monitor_name} monitor: {e}")
        return {
            "success": False,
            "monitor": monitor_name,
            "changes": None,
            "error": str(e),
        }


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Run all exchange documentation monitors"
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
    parser.add_argument(
        "--notify-no_sections",
        action="store_true",
        dest="notify_no_sections",
        default=None,
        help="Enable Telegram notifications when no sections are found for an exchange to monitor (default: enabled)",
    )
    parser.add_argument(
        "--no-notify-no_sections",
        action="store_false",
        dest="notify_no_sections",
        help="Disable Telegram notifications when no sections are found for an exchange to monitor",
    )
    parser.add_argument(
        "--notify_many_deletions",
        action="store_true",
        dest="notify_many_deletions",
        default=None,
        help="Enable Telegram notifications when many sections of an exchanges documentation are deleted (default: enabled)",
    )
    parser.add_argument(
        "--no-notify_many_deletions",
        action="store_false",
        dest="notify_many_deletions",
        help="Disable Telegram notifications when many sections of an exchanges documentation are deleted",
    )
    parser.add_argument(
        "--notify_many_deletions_threshold",
        dest="notify_many_deletions_threshold",
        default=0.2,
        help="Threshold for notify_many_deletions (default: 0.2)",
    )
    parser.add_argument(
        "--no-save-content",
        action="store_true",
        help="Don't save full section content (reduces storage)",
    )
    parser.add_argument(
        "--exchanges",
        nargs="+",
        choices=[
            "binance",
            "bitget",
            "bitmex",
            "bybit",
            "coinbase",
            "deribit",
            "hyperliquid",
            "kraken",
            "lighter",
            "okx",
            "all",
        ],
        default=["all"],
        help="Which exchanges to monitor (default: all)",
    )

    args = parser.parse_args()

    # Set up logger for run_all
    logger = setup_logger("run_all")

    # Get Telegram credentials
    class DummyArgs:
        def __init__(
            self,
            config,
            telegram_token,
            telegram_chat_id,
            no_telegram,
            notify_additions,
            notify_modifications,
            notify_deletions,
            notify_no_sections,
            notify_many_deletions,
            notify_many_deletions_threshold,
        ):
            self.config = config
            self.telegram_token = telegram_token
            self.telegram_chat_id = telegram_chat_id
            self.no_telegram = no_telegram
            self.notify_additions = notify_additions
            self.notify_modifications = notify_modifications
            self.notify_deletions = notify_deletions
            self.notify_no_sections = notify_no_sections
            self.notify_many_deletions = notify_many_deletions
            self.notify_many_deletions_threshold = notify_many_deletions_threshold

    dummy_args = DummyArgs(
        args.config,
        args.telegram_token,
        args.telegram_chat_id,
        args.no_telegram,
        args.notify_additions,
        args.notify_modifications,
        args.notify_deletions,
        args.notify_no_sections,
        args.notify_many_deletions,
        args.notify_many_deletions_threshold,
    )
    telegram_token, telegram_chat_id = BaseDocMonitor.get_telegram_credentials(
        dummy_args
    )

    # Get notification settings
    notify_additions, notify_modifications, notify_deletions, notify_no_sections, notify_many_deletions, notify_many_deletions_threshold = (
        BaseDocMonitor.get_notification_settings(dummy_args)
    )

    # Determine which exchanges to run
    exchanges_to_run = set(args.exchanges)
    if "all" in exchanges_to_run:
        exchanges_to_run = {
            "binance",
            "bitget",
            "bitmex",
            "bybit",
            "coinbase",
            "deribit",
            "hyperliquid",
            "kraken",
            "lighter",
            "okx",
        }

    # Monitor configuration
    monitors_config = []

    # Common kwargs for all monitors
    common_kwargs = {
        "telegram_bot_token": telegram_token,
        "telegram_chat_id": telegram_chat_id,
        "notify_additions": notify_additions,
        "notify_modifications": notify_modifications,
        "notify_deletions": notify_deletions,
        "notify_no_sections": notify_no_sections,
        "notify_many_deletions": notify_many_deletions,
        "notify_many_deletions_threshold": notify_many_deletions_threshold,
    }

    if "binance" in exchanges_to_run:
        monitors_config.append(
            {
                "class": BinanceDocMonitor,
                "name": "Binance",
                "kwargs": {**common_kwargs},
            }
        )

    if "bitget" in exchanges_to_run:
        monitors_config.append(
            {
                "class": BitgetDocMonitor,
                "name": "Bitget",
                "kwargs": {**common_kwargs},
            }
        )

    if "bitmex" in exchanges_to_run:
        monitors_config.append(
            {
                "class": BitmexDocMonitor,
                "name": "BitMEX",
                "kwargs": {**common_kwargs},
            }
        )

    if "bybit" in exchanges_to_run:
        monitors_config.append(
            {
                "class": BybitDocMonitor,
                "name": "Bybit",
                "kwargs": {**common_kwargs},
            }
        )

    if "coinbase" in exchanges_to_run:
        monitors_config.append(
            {
                "class": CoinbaseDocMonitor,
                "name": "Coinbase",
                "kwargs": {**common_kwargs},
            }
        )

    if "deribit" in exchanges_to_run:
        monitors_config.append(
            {
                "class": DeribitDocMonitor,
                "name": "Deribit",
                "kwargs": {
                    "telegram_bot_token": telegram_token,
                    "telegram_chat_id": telegram_chat_id,
                    "notify_additions": notify_additions,
                    "notify_modifications": False,
                    "notify_deletions": notify_deletions,
                },
            }
        )

    if "hyperliquid" in exchanges_to_run:
        monitors_config.append(
            {
                "class": HyperliquidDocMonitor,
                "name": "Hyperliquid",
                "kwargs": {**common_kwargs},
            }
        )

    if "kraken" in exchanges_to_run:
        monitors_config.append(
            {
                "class": KrakenDocMonitor,
                "name": "Kraken",
                "kwargs": {**common_kwargs},
            }
        )

    if "lighter" in exchanges_to_run:
        monitors_config.append(
            {
                "class": LighterDocMonitor,
                "name": "Lighter",
                "kwargs": {**common_kwargs},
            }
        )

    if "okx" in exchanges_to_run:
        monitors_config.append(
            {
                "class": OKXDocMonitor,
                "name": "OKX",
                "kwargs": {**common_kwargs},
            }
        )

    # Run all monitors
    logger.info("=" * 80)
    logger.info("Exchange Documentation Monitor Suite")
    logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Monitoring {len(monitors_config)} exchange(s)")
    logger.info("=" * 80)

    results = []
    for config in monitors_config:
        result = run_monitor(
            config["class"],
            config["name"],
            logger,
            save_content=not args.no_save_content,
            **config["kwargs"],
        )
        results.append(result)

    # Print summary
    logger.info("=" * 80)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 80)

    total_changes = 0
    successful_monitors = 0
    failed_monitors = 0

    for result in results:
        if result["success"]:
            successful_monitors += 1
            changes = result["changes"]
            change_count = (
                len(changes["new_sections"])
                + len(changes["modified_sections"])
                + len(changes["deleted_sections"])
            )
            total_changes += change_count

            status = "✅" if change_count == 0 else f"⚠️  {change_count} change(s)"
            logger.info(f"  {result['monitor']}: {status}")
        else:
            failed_monitors += 1
            logger.error(f"  {result['monitor']}: ❌ Failed - {result['error']}")

    logger.info(f"Total monitors run: {len(results)}")
    logger.info(f"Successful: {successful_monitors}")
    logger.info(f"Failed: {failed_monitors}")
    logger.info(f"Total changes detected: {total_changes}")
    logger.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Exit with error code if any monitors failed
    if failed_monitors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
