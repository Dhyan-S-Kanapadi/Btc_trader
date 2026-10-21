"""Temporary command-line entrypoint for future paper-trading services."""

# ruff: noqa: E501

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
    subcommands.add_parser("seed-accounts", help="Idempotently seed paper accounts A through D.")
    replay = subcommands.add_parser("replay", help="Run an offline paper-trading replay.")
    replay.add_argument("--source", choices=("synthetic", "db"), default="synthetic")
    replay.add_argument("--seed", type=int, default=1)
    replay.add_argument("--bars", type=int, default=3000)
    replay.add_argument("--start", help="Inclusive UTC ISO-8601 timestamp for database replay.")
    replay.add_argument("--end", help="Inclusive UTC ISO-8601 timestamp for database replay.")
    replay.add_argument("--accounts", default="A", help="Comma-separated seeded paper accounts.")
    replay.add_argument("--policy", choices=("take_all", "volume_filter"), default="take_all")
    replay.add_argument("--output-dir", type=Path, default=Path("replay-output"))
    replay.add_argument("--persist", action="store_true")
    report = subcommands.add_parser("report", help="Write a read-only account comparison report.")
    report.add_argument(
        "--accounts", help="Comma-separated accounts; defaults to all configured accounts."
    )
    report.add_argument("--start", help="Inclusive UTC ISO-8601 timestamp.")
    report.add_argument("--end", help="Inclusive UTC ISO-8601 timestamp.")
    report.add_argument("--output-dir", type=Path, default=Path("report-output"))
    for command in ("worker", "api"):
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

    if args.command == "seed-accounts":
        from trader.config import Settings
        from trader.db.storage import PostgresStorage

        settings = Settings()
        if settings.database_url is None:
            parser.error("DATABASE_URL is required for trader seed-accounts")
        storage = PostgresStorage(settings.database_url)
        for account_id, policy_name in (
            ("A", "take_all"),
            ("B", "skip_all"),
            ("C", "skip_all"),
            ("D", "skip_all"),
        ):
            storage.seed_account(
                account_id,
                settings.risk.starting_equity,
                {
                    "account_id": account_id,
                    "label": f"Paper account {account_id}",
                    "policy_name": policy_name,
                    "starting_equity": str(settings.risk.starting_equity),
                    "enabled": True,
                },
            )
        configure_logging().info("paper accounts seeded", extra={"command": "seed-accounts"})
        return 0

    if args.command == "replay":
        from trader.config import Settings
        from trader.db.storage import PostgresStorage
        from trader.replay import (
            AccountConfig,
            TakeAllPolicy,
            VolumeFilterPolicy,
            generate_candles,
            load_account_state,
            persist_routed_candle,
            refuse_nonempty_account,
            run_replay,
            run_routed_replay,
            write_combined_summary,
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
        storage = None if base.database_url is None else PostgresStorage(base.database_url)
        if args.source == "synthetic":
            candles = generate_candles(
                args.seed, args.bars, datetime(2026, 1, 1, tzinfo=UTC), settings.strategy.interval
            )
        else:
            if storage is None:
                parser.error("DATABASE_URL is required for database replay")
            start = datetime.fromisoformat(args.start).astimezone(UTC) if args.start else None
            end = datetime.fromisoformat(args.end).astimezone(UTC) if args.end else None
            candles = storage.load_candles(
                settings.strategy.symbol, settings.strategy.interval, start, end
            )
        account_ids = tuple(part.strip() for part in args.accounts.split(",") if part.strip())
        if not account_ids or len(set(account_ids)) != len(account_ids):
            parser.error("--accounts must contain unique account IDs")
        if account_ids == ("A",) and not args.persist:
            policy = (
                TakeAllPolicy()
                if args.policy == "take_all"
                else VolumeFilterPolicy(settings.strategy.volume_ratio_min)
            )
            result = run_replay(candles, policy, settings, "A")
            write_output(args.output_dir, result, settings, args.seed, args.policy, args.source)
            configure_logging().info(
                "replay complete",
                extra={
                    "source": args.source.upper(),
                    "accounts": ["A"],
                    "trades": len(result.trades),
                },
            )
            return 0
        if storage is None:
            parser.error("DATABASE_URL is required for multi-account or persisted replay")
        try:
            account_configs = {
                account_id: AccountConfig.model_validate(storage.load_account_config(account_id))
                for account_id in account_ids
            }
        except (LookupError, ValueError) as error:
            parser.error(f"invalid account configuration: {error}")
        if args.persist:
            for account_id in account_ids:
                refuse_nonempty_account(storage, account_id)
        results = run_routed_replay(
            candles,
            {
                account_id: (load_account_state(storage, account), account)
                for account_id, account in account_configs.items()
            },
            settings,
            (
                lambda candle, routed: persist_routed_candle(
                    storage, settings.strategy.interval, candle, routed
                )
            )
            if args.persist
            else None,
        )
        for account_id, result in results.items():
            write_output(
                args.output_dir / account_id,
                result,
                settings,
                args.seed,
                account_configs[account_id].policy_name,
                args.source,
            )
        write_combined_summary(args.output_dir, results)
        if args.persist:
            storage.save_run_metadata(
                "SYNTHETIC_REPLAY" if args.source == "synthetic" else "REPLAY",
                {"source": args.source, "seed": args.seed, "accounts": list(account_ids)},
            )
        configure_logging().info(
            "replay complete",
            extra={
                "source": args.source.upper(),
                "accounts": list(account_ids),
                "trades": sum(len(result.trades) for result in results.values()),
            },
        )
        return 0

    if args.command == "report":
        from trader.config import Settings
        from trader.db.storage import PostgresStorage
        from trader.report.service import build_report, write_report

        settings = Settings()
        if settings.database_url is None:
            parser.error("DATABASE_URL is required for trader report")
        storage = PostgresStorage(settings.database_url)
        account_ids = (
            [part.strip() for part in args.accounts.split(",") if part.strip()]
            if args.accounts
            else storage.report_account_ids()
        )
        if not account_ids:
            parser.error("no configured accounts")
        start = datetime.fromisoformat(args.start).astimezone(UTC) if args.start else None
        end = datetime.fromisoformat(args.end).astimezone(UTC) if args.end else None
        metrics, warnings, metadata = build_report(storage, account_ids, start, end)
        if not any(
            value.trade_count or value.total_return is not None for value in metrics.values()
        ):
            parser.error("no report data for selected accounts")
        write_report(
            args.output_dir, metrics, warnings, metadata, settings.report.report_min_trades
        )
        configure_logging().info("report complete", extra={"accounts": account_ids})
        return 0

    if args.command == "worker":
        from trader.config import Settings
        from trader.worker import run_worker

        return run_worker(Settings())

    issue = _COMMAND_ISSUES[args.command]
    configure_logging().error(
        f"not implemented yet (issue #{issue})",
        extra={"command": args.command, "issue": issue},
    )
    return 1
