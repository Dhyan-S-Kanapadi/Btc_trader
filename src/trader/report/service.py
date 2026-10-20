"""Thin read-only Postgres adapter and deterministic report exporters."""

# ruff: noqa: E501

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from trader.db.storage import PostgresStorage
from trader.models import Trade

from .metrics import AccountMetrics, EquityPoint, calculate_metrics


def build_report(
    storage: PostgresStorage, account_ids: list[str], start: datetime | None, end: datetime | None
) -> tuple[dict[str, AccountMetrics], list[str], dict[str, object]]:
    """Load Postgres rows without mutation and calculate one metric set per account."""

    metrics: dict[str, AccountMetrics] = {}
    candidate_sets: list[set[str]] = []
    ranges: list[tuple[datetime | None, datetime | None]] = []
    metadata: dict[str, object] = {}
    for account_id in account_ids:
        trades, equity, keys, candle_range, rejected, open_positions, config, run = (
            storage.load_report_rows(account_id, start, end)
        )
        if config is not None:
            metadata.setdefault("configs", {})[account_id] = config
        if run is not None:
            metadata = {**metadata, **run}
        metrics[account_id] = calculate_metrics(
            [
                Trade(
                    account_id=row.account_id,
                    symbol=row.symbol,
                    qty=row.qty,
                    entry_price=row.entry_price,
                    entry_time=row.entry_time.astimezone(UTC),
                    stop_price=row.stop_price,
                    initial_stop_price=row.initial_stop_price,
                    exit_price=row.exit_price,
                    exit_time=row.exit_time.astimezone(UTC),
                    fees=row.fees,
                    reason=row.reason,
                )
                for row in trades
                if row.initial_stop_price is not None
            ],
            [EquityPoint(row.recorded_at.astimezone(UTC), row.equity) for row in equity],
            open_positions,
            rejected,
        )
        candidate_sets.append(set(keys))
        ranges.append(candle_range)
    warnings: list[str] = []
    if len({frozenset(values) for values in candidate_sets}) > 1 or len(set(ranges)) > 1:
        warnings.append(
            "WARNING: comparison is not like-for-like; candidate sets or candle ranges differ."
        )
    if metadata.get("source") == "synthetic":
        warnings.append("SYNTHETIC: this is toy data, not market data or a performance result.")
    return metrics, warnings, metadata


def write_report(
    output_dir: Path,
    metrics: dict[str, AccountMetrics],
    warnings: list[str],
    metadata: dict[str, object],
    minimum_trades: int,
) -> dict[str, Path]:
    """Write byte-stable CSV, JSON, and Markdown report files without wall-clock data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    sample_warnings = [
        f"WARNING: {account_id} has {value.trade_count} closed trades; below assumed minimum {minimum_trades}."
        for account_id, value in metrics.items()
        if value.trade_count < minimum_trades
    ]
    all_warnings = sorted(warnings + sample_warnings)
    data = {
        "paper_trading_only": True,
        "warnings": all_warnings,
        "cost_assumptions": metadata.get("costs", "MISSING from stored run metadata"),
        "strategy_parameters": metadata.get("strategy", "MISSING from stored run metadata"),
        "accounts": {account_id: _record(value) for account_id, value in sorted(metrics.items())},
        "delta_vs_A": {
            account_id: _deltas(value, metrics.get("A"))
            for account_id, value in sorted(metrics.items())
        },
    }
    json_path = output_dir / "report.json"
    json_path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":"), default=str), encoding="utf-8"
    )
    csv_path = output_dir / "report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        fields = [
            "account_id",
            "trade_count",
            "total_return",
            "max_drawdown",
            "profit_factor",
            "fees_paid",
            "cost_assumptions",
            "warnings",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for account_id, value in sorted(metrics.items()):
            writer.writerow(
                {
                    "account_id": account_id,
                    "trade_count": value.trade_count,
                    "total_return": value.total_return,
                    "max_drawdown": value.max_drawdown,
                    "profit_factor": value.profit_factor,
                    "fees_paid": value.fees_paid,
                    "cost_assumptions": data["cost_assumptions"],
                    "warnings": " | ".join(all_warnings),
                }
            )
    markdown = [
        "# PAPER TRADING ONLY — Variant report",
        "",
        *all_warnings,
        "",
        f"Cost assumptions: {data['cost_assumptions']}",
        f"Strategy parameters: {data['strategy_parameters']}",
        "",
        "| Account | Closed trades | Return | Max drawdown | Profit factor | Fees |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for account_id, value in sorted(metrics.items()):
        markdown.append(
            f"| {account_id} | {value.trade_count} | {_percent(value.total_return)} | {_percent(value.max_drawdown)} | {value.profit_factor if value.profit_factor is not None else 'null (no losing trades)'} | {value.fees_paid} |"
        )
    markdown.extend(["", "No significance or confidence intervals are calculated."])
    markdown_path = output_dir / "report.md"
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "markdown": markdown_path}


def _record(value: AccountMetrics) -> dict[str, object]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _percent(value: object) -> str:
    return "null" if value is None else f"{value * 100}%"


def _deltas(value: AccountMetrics, baseline: AccountMetrics | None) -> dict[str, object]:
    """Return requested side-by-side deltas without implying statistical significance."""

    if baseline is None:
        return {
            "total_return": None,
            "trade_count": None,
            "max_drawdown": None,
            "profit_factor": None,
        }
    return {
        "total_return": _subtract(value.total_return, baseline.total_return),
        "trade_count": value.trade_count - baseline.trade_count,
        "max_drawdown": value.max_drawdown - baseline.max_drawdown,
        "profit_factor": _subtract(value.profit_factor, baseline.profit_factor),
    }


def _subtract(value: object, baseline: object) -> object:
    return None if value is None or baseline is None else value - baseline
