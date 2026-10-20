"""Deterministic local files for offline replay results."""

import csv
import json
from pathlib import Path
from typing import Any

from trader.config import Settings

from .runner import ReplayResult


def write_output(
    output_dir: Path,
    result: ReplayResult,
    config: Settings,
    seed: int,
    policy: str,
    source: str = "synthetic",
) -> dict[str, Path]:
    """Write stable replay files without wall-clock data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, list[dict[str, Any]]] = {
        "trades": [trade.model_dump(mode="json") for trade in result.trades],
        "equity": [point.model_dump(mode="json") for point in result.equity],
        "decisions": [decision.model_dump(mode="json") for decision in result.decisions],
    }
    paths: dict[str, Path] = {}
    for name, rows in records.items():
        prefix = "SYNTHETIC_" if source == "synthetic" else ""
        json_path = output_dir / f"{prefix}{name}.json"
        json_path.write_text(
            json.dumps(rows, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        paths[f"{name}_json"] = json_path
        csv_path = output_dir / f"{prefix}{name}.csv"
        _write_csv(csv_path, rows)
        paths[f"{name}_csv"] = csv_path
    summary = {
        "label": "SYNTHETIC - NOT MARKET DATA OR A PERFORMANCE RESULT"
        if source == "synthetic"
        else "DATABASE_REPLAY",
        "source": source,
        "seed": seed,
        "policy": policy,
        "trades": len(result.trades),
        "final_equity": str(result.state.risk.equity),
        "config": config.model_dump(mode="json"),
    }
    path = output_dir / (
        "SYNTHETIC_run_summary.json" if source == "synthetic" else "run_summary.json"
    )
    path.write_text(json.dumps(summary, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    paths["summary"] = path
    return paths


def write_combined_summary(output_dir: Path, results: dict[str, ReplayResult]) -> Path:
    """Write the small deterministic cross-account summary for a routed replay."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "combined_summary.json"
    path.write_text(
        json.dumps(
            {
                account_id: {
                    "trades": len(result.trades),
                    "decisions": len(result.decisions),
                    "final_equity": str(result.state.risk.equity),
                }
                for account_id, result in sorted(results.items())
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )
