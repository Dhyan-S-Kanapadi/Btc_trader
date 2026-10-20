"""Temporary command-line entrypoint for future paper-trading services."""

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    replay = subcommands.add_parser("replay", help="Run an offline paper-trading replay.")
    replay.add_argument("--source", choices=("synthetic", "db"), default="synthetic")
    replay.add_argument("--seed", type=int, default=1)
    replay.add_argument("--bars", type=int, default=3000)
    replay.add_argument("--start", help="Inclusive UTC ISO-8601 timestamp for database replay.")
    replay.add_argument("--end", help="Inclusive UTC ISO-8601 timestamp for database replay.")
    replay.add_argument("--account", default="A")
    replay.add_argument("--policy", choices=("take_all", "volume_filter"), default="take_all")
    replay.add_argument("--output-dir", type=Path, default=Path("replay-output"))
    replay.add_argument("--persist", action="store_true")
    for command in ("worker", "api", "report"):
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

    if args.command == "replay":
        from trader.config import Settings
        from trader.db.storage import PostgresStorage
        from trader.replay import (
            TakeAllPolicy,
            VolumeFilterPolicy,
            generate_candles,
            persist_replay,
            refuse_nonempty_account,
            run_replay,
            write_output,
        )

        if args.bars <= 0:
            parser.error("--bars must be positive")
        base = Settings()
        settings = (
            base
            if args.source == "db"
            else base.model_copy(
                update={"strategy": base.strategy.model_copy(update={"symbol": "SYNTH-BTC"})}
            )
        )
        policy = (
            TakeAllPolicy()
            if args.policy == "take_all"
            else VolumeFilterPolicy(settings.strategy.volume_ratio_min)
        )
        storage = None
        if args.source == "synthetic":
            candles = generate_candles(
                args.seed, args.bars, datetime(2026, 1, 1, tzinfo=UTC), settings.strategy.interval
            )
        else:
            if base.database_url is None:
                parser.error("DATABASE_URL is required for database replay")
            storage = PostgresStorage(base.database_url)
            start = datetime.fromisoformat(args.start).astimezone(UTC) if args.start else None
            end = datetime.fromisoformat(args.end).astimezone(UTC) if args.end else None
            candles = storage.load_candles(
                settings.strategy.symbol, settings.strategy.interval, start, end
            )
        result = run_replay(candles, policy, settings, args.account)
        write_output(args.output_dir, result, settings, args.seed, args.policy, args.source)
        if args.persist:
            if storage is None:
                if base.database_url is None:
                    parser.error("DATABASE_URL is required for --persist")
                storage = PostgresStorage(base.database_url)
            refuse_nonempty_account(storage, args.account)
            persist_replay(
                storage,
                candles,
                settings.strategy.interval,
                result,
                {"source": args.source, "seed": args.seed, "policy": args.policy},
            )
        configure_logging().info(
            "replay complete",
            extra={
                "source": args.source.upper(),
                "trades": len(result.trades),
                "final_equity": str(result.state.risk.equity),
            },
        )
        return 0

    issue = _COMMAND_ISSUES[args.command]
    configure_logging().error(
        f"not implemented yet (issue #{issue})",
        extra={"command": args.command, "issue": issue},
    )
    return 1
