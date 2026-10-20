"""Temporary command-line entrypoint for future paper-trading services."""

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from trader.logging import configure_logging

_COMMAND_ISSUES = {
    "worker": 13,
    "api": 14,
    "replay": 10,
    "report": 12,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the paper-trader CLI parser without implementing any service logic."""

    parser = argparse.ArgumentParser(prog="trader", description="Paper-trading research CLI.")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("migrate", help="Apply database migrations.")
    backfill = subcommands.add_parser("backfill", help="Fetch public closed market-data candles.")
    backfill.add_argument("--days", type=int, help="Number of days to backfill.")
    for command in _COMMAND_ISSUES:
        subcommands.add_parser(command, help=f"Reserved for issue #{_COMMAND_ISSUES[command]}.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a stub command and return its process exit status."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "migrate":
        from trader.config import Settings
        from trader.db.migrations import upgrade_head

        database_url = Settings().database_url
        if database_url is None:
            parser.error("DATABASE_URL is required for trader migrate")
        upgrade_head(database_url)
        configure_logging().info("database migrated", extra={"command": "migrate"})
        return 0

    if args.command == "backfill":
        from trader.config import Settings
        from trader.data.binance import BinanceIngestor
        from trader.db.storage import PostgresStorage

        settings = Settings()
        if settings.database_url is None:
            parser.error("DATABASE_URL is required for trader backfill")
        days = args.days or settings.data.backfill_days
        if days <= 0:
            parser.error("--days must be positive")
        now = datetime.now(UTC)
        ingestor = BinanceIngestor(settings.data)
        try:
            written = ingestor.backfill(
                PostgresStorage(settings.database_url),
                settings.strategy.symbol,
                settings.strategy.interval,
                now - timedelta(days=days),
                now,
                now,
            )
        finally:
            ingestor.close()
        configure_logging().info(
            "backfill complete", extra={"command": "backfill", "written": written}
        )
        return 0

    issue = _COMMAND_ISSUES[args.command]
    configure_logging().error(
        f"not implemented yet (issue #{issue})",
        extra={"command": args.command, "issue": issue},
    )
    return 1
