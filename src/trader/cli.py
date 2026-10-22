"""Temporary command-line entrypoint for future paper-trading services."""

# ruff: noqa: E501

import argparse
import getpass
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
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
    replay.add_argument(
        "--control", type=Path, help="Offline JSON control snapshot; never read from DB."
    )
    report = subcommands.add_parser("report", help="Write a read-only account comparison report.")
    report.add_argument(
        "--accounts", help="Comma-separated accounts; defaults to all configured accounts."
    )
    report.add_argument("--start", help="Inclusive UTC ISO-8601 timestamp.")
    report.add_argument("--end", help="Inclusive UTC ISO-8601 timestamp.")
    report.add_argument("--output-dir", type=Path, default=Path("report-output"))
    subcommands.add_parser("worker", help=f"Reserved for issue #{_COMMAND_ISSUES['worker']}.")
    subcommands.add_parser("api", help="Run the read-only paper-trading HTTP API.")
    news = subcommands.add_parser("news", help="Run isolated BLS forward-test ingestion.")
    news_commands = news.add_subparsers(dest="news_command", required=True)
    news_commands.add_parser("poll", help="Perform one bounded BLS poll.").add_argument(
        "--once", action="store_true", required=True
    )
    news_commands.add_parser("run", help="Poll BLS until SIGTERM or SIGINT.")
    news_commands.add_parser(
        "show", help="Show clean/flagged BLS data visible as of UTC."
    ).add_argument("--as-of", required=True)
    jev = subcommands.add_parser("jev", help="Inspect isolated Jev-sensor calibration inputs.")
    jev_commands = jev.add_subparsers(dest="jev_command", required=True)
    calibrate = jev_commands.add_parser(
        "calibrate", help="Summarize human-label readiness; no model call."
    )
    calibrate.add_argument(
        "--labels", type=Path, default=Path("spikes/news_jev/labeling_sheet.csv")
    )
    memory = subcommands.add_parser("memory", help="Manage separate, agent-only episodic memory.")
    memory_subcommands = memory.add_subparsers(dest="memory_command", required=True)
    memory_subcommands.add_parser("init", help="Initialize pgvector memory schema and roles.")
    sync_memory = memory_subcommands.add_parser(
        "sync", help="Copy resolved Account A outcomes to memory."
    )
    sync_memory.add_argument("--namespace", default=None)
    sync_memory.add_argument("--outcome-account", default="A")
    sync_memory.add_argument("--synthetic", action="store_true")
    sync_memory.add_argument("--since", help="Inclusive UTC ISO-8601 exit time.")
    search_memory = memory_subcommands.add_parser(
        "search", help="Inspect time-gated memory retrieval."
    )
    search_memory.add_argument("--as-of", required=True, help="UTC ISO-8601 candidate time.")
    search_memory.add_argument("--snapshot", type=Path, required=True, help="Snapshot JSON file.")
    search_memory.add_argument("--k", type=int, help="Number of exact nearest episodes.")
    control = subcommands.add_parser(
        "control", help="Inspect or change fail-closed agent controls."
    )
    control_subcommands = control.add_subparsers(dest="control_command", required=True)
    control_subcommands.add_parser("show", help="Show the current control snapshot.")
    control_subcommands.add_parser(
        "seed", help="Create conservative defaults without overwriting changes."
    )
    set_control = control_subcommands.add_parser(
        "set", help="Atomically change one allowlisted control."
    )
    set_control.add_argument("scope", help="global or an account ID")
    set_control.add_argument("field")
    set_control.add_argument("value")
    set_control.add_argument(
        "--actor", default=getpass.getuser(), help="Self-reported operator identity."
    )
    for name, value in (("kill", "true"), ("unkill", "false")):
        command = control_subcommands.add_parser(name, help=f"Set a kill switch {value}.")
        command.add_argument("scope", help="global or an account ID")
        command.add_argument(
            "--actor", default=getpass.getuser(), help="Self-reported operator identity."
        )
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
        for account_id, policy_name, variant in (
            ("A", "take_all", "base"),
            ("B", "agent_veto", "base"),
            ("C", "agent_veto", "jev"),
            ("D", "agent_veto", "memory"),
        ):
            storage.seed_account(
                account_id,
                settings.risk.starting_equity,
                {
                    "account_id": account_id,
                    "label": f"Paper account {account_id}",
                    "policy_name": policy_name,
                    "variant": variant,
                    "starting_equity": str(settings.risk.starting_equity),
                    "enabled": True,
                    "risk": settings.risk.model_dump(mode="json"),
                },
            )
            if account_id in {"B", "C", "D"}:
                storage.promote_placeholder_policy(
                    account_id, policy_name, variant, getpass.getuser()
                )
        configure_logging().info("paper accounts seeded", extra={"command": "seed-accounts"})
        return 0

    if args.command == "control":
        from trader.config import Settings
        from trader.db.storage import PostgresStorage

        settings = Settings()
        if settings.database_url is None:
            parser.error("DATABASE_URL is required for trader control")
        storage = PostgresStorage(settings.database_url)
        if args.control_command == "seed":
            storage.seed_agent_controls()
            return 0
        if args.control_command == "show":
            print(storage.load_agent_control().model_dump(mode="json"))
            return 0
        field = "kill_switch" if args.control_command in {"kill", "unkill"} else args.field
        raw_value = (
            "true"
            if args.control_command == "kill"
            else "false"
            if args.control_command == "unkill"
            else args.value
        )
        bool_fields = {"agent_enabled", "kill_switch", "shadow", "jev_enabled", "memory_enabled"}
        decimal_fields = {"per_candidate_cap", "per_day_cap"}
        try:
            if field in bool_fields:
                if raw_value.lower() not in {"true", "false"}:
                    raise ValueError("must be true or false")
                value: object = raw_value.lower() == "true"
            elif field in decimal_fields:
                value = Decimal(raw_value)
                if value < 0:
                    raise ValueError("must be non-negative")
                value = str(value)
            elif field in {"model_version", "prompt_version", "fallback_policy"}:
                if field == "fallback_policy" and raw_value != "skip_all":
                    raise ValueError("only skip_all fallback is supported")
                value = raw_value
            else:
                raise ValueError("field is not allowed")
        except (InvalidOperation, ValueError) as error:
            parser.error(f"invalid control value: {error}")
        storage.seed_agent_controls()
        storage.set_agent_control(args.scope, field, value, args.actor)
        return 0

    if args.command == "memory":
        from trader.config import Settings
        from trader.memory import embed_snapshot, embedding_version, record_episode
        from trader.memory.postgres import PostgresMemorySource, PostgresMemoryWriter
        from trader.models import Candidate, Snapshot, Trade

        settings = Settings()
        read_url = settings.agent_memory.database_url
        if args.memory_command == "init":
            import psycopg

            write_url = settings.agent_memory.write_database_url
            if write_url is None:
                parser.error("AGENT_MEMORY_WRITE_DATABASE_URL is required for trader memory init")

            # The source checkout is the supported local command target; deployments run this SQL once.
            path = Path("sql/agent_memory_init.sql")
            if not path.is_file():
                parser.error("sql/agent_memory_init.sql is required from the repository root")
            with psycopg.connect(
                write_url.replace("postgresql+psycopg://", "postgresql://", 1)
            ) as con:
                con.execute(path.read_text(encoding="utf-8"))
            return 0
        if args.memory_command == "sync":
            import psycopg
            from psycopg.rows import dict_row

            write_url = settings.agent_memory.write_database_url
            if write_url is None:
                parser.error("AGENT_MEMORY_WRITE_DATABASE_URL is required for trader memory sync")
            if settings.database_url_readonly is None:
                parser.error("DATABASE_URL_READONLY is required for trader memory sync")
            since = datetime.fromisoformat(args.since).astimezone(UTC) if args.since else None
            query = """
                SELECT c.symbol, c.bar_index, c.signal_time, c.reference_price, c.atr,
                       c.breakout_level, c.idempotency_key, s.snapshot,
                       t.account_id, t.qty, t.entry_price, t.entry_time, t.stop_price,
                       t.initial_stop_price, t.exit_price, t.exit_time, t.fees, t.reason,
                       exit_candle.open_time + interval '1 hour' AS known_at
                FROM trades t
                JOIN candidates c ON c.idempotency_key = t.candidate_idempotency_key
                JOIN snapshots s ON s.candidate_id = c.id
                JOIN candles exit_candle ON exit_candle.symbol = t.symbol
                    AND exit_candle.interval = '1h' AND exit_candle.open_time = t.exit_time
                WHERE t.account_id = %s AND t.candidate_idempotency_key IS NOT NULL
                  AND (%s::timestamptz IS NULL OR t.exit_time >= %s::timestamptz)
                ORDER BY known_at, t.id
            """
            readonly_url = settings.database_url_readonly.replace(
                "postgresql+psycopg://", "postgresql://", 1
            )
            with psycopg.connect(readonly_url, row_factory=dict_row) as connection:
                rows = connection.execute(query, (args.outcome_account, since, since)).fetchall()
            namespace = args.namespace or settings.agent_memory.namespace
            episodes = []
            for row in rows:
                candidate = Candidate.model_validate(
                    {key: row[key] for key in Candidate.model_fields}
                )
                snapshot = Snapshot.model_validate(row["snapshot"])
                trade = Trade.model_validate(
                    {key: row[key] for key in Trade.model_fields if key in row}
                )
                episode = record_episode(
                    candidate,
                    snapshot,
                    trade,
                    row["known_at"],
                    namespace=namespace,
                    synthetic=args.synthetic,
                    config=settings.agent_memory,
                )
                if episode is not None:
                    episodes.append(episode)
            print(
                json.dumps(
                    {"inserted": PostgresMemoryWriter(write_url).insert(episodes)}, sort_keys=True
                )
            )
            return 0
        if read_url is None:
            parser.error("AGENT_MEMORY_DATABASE_URL is required for trader memory search")
        as_of = datetime.fromisoformat(args.as_of).astimezone(UTC)
        snapshot = Snapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
        if snapshot.signal_time != as_of:
            parser.error("--as-of must equal snapshot.signal_time")
        vector = embed_snapshot(snapshot, settings.agent_memory)
        if vector is None:
            print(json.dumps({"items": [], "found": 0, "reason": "not_embeddable"}))
            return 0
        rows = PostgresMemorySource(read_url).search(
            as_of=as_of,
            candidate_key=snapshot.idempotency_key,
            namespace=settings.agent_memory.namespace,
            embedding=vector,
            embedding_version=embedding_version(settings.agent_memory),
            k=args.k or settings.agent_memory.k_cap,
            max_distance=settings.agent_memory.max_distance,
        )
        print(json.dumps({"items": rows, "found": len(rows)}, default=str, sort_keys=True))
        return 0

    if args.command == "replay":
        from trader.config import Settings
        from trader.control import ControlConfig
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
            ControlConfig.model_validate(json.loads(args.control.read_text()))
            if args.control
            else ControlConfig(),
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
        from trader.variant_runtime import VariantEvidenceProvider
        from trader.worker import run_worker

        settings = Settings()
        return run_worker(settings, evidence_provider=VariantEvidenceProvider(settings))

    if args.command == "api":
        from trader.api import run_api
        from trader.config import Settings

        return run_api(Settings())

    if args.command == "news":
        from trader.config import Settings
        from trader.db.storage import PostgresStorage
        from trader.news.service import poll_once, run, show
        from trader.news.sources import BlsCalendarSource

        settings = Settings()
        if settings.database_url is None:
            parser.error("DATABASE_URL is required for trader news")
        storage = PostgresStorage(settings.database_url)
        if args.news_command == "poll":
            source = BlsCalendarSource(settings.news)
            try:
                print(json.dumps(poll_once(storage, settings.news, source), sort_keys=True))
            finally:
                source.close()
            return 0
        if args.news_command == "run":
            return run(storage, settings.news)
        try:
            as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            parser.error("--as-of must be an ISO-8601 UTC timestamp")
        print(show(storage, settings.news, as_of).model_dump_json())
        return 0

    if args.command == "jev":
        import csv

        try:
            with args.labels.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
        except OSError as error:
            parser.error(f"cannot read labels: {error}")
        labeled = sum(
            bool(row.get("event_within_4h_label") or row.get("news_tone_label")) for row in rows
        )
        print(
            json.dumps(
                {
                    "rows": len(rows),
                    "labeled": labeled,
                    "status": "insufficient_labels" if not labeled else "labels_present",
                },
                sort_keys=True,
            )
        )
        return 0

    issue = _COMMAND_ISSUES[args.command]
    configure_logging().error(
        f"not implemented yet (issue #{issue})",
        extra={"command": args.command, "issue": issue},
    )
    return 1
