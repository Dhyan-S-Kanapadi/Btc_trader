"""Typed tool registry that binds the model to a harness-selected as-of timestamp."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from trader.config import Settings
from trader.data.binance import interval_delta
from trader.models import Candle
from trader.strategy import atr_at, evaluate_candle

from .source import CandleSource, ToolError, enforce_as_of


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VolumeInput(_Input):
    lookback_bars: int | None = Field(default=None, gt=0)


class TrendInput(_Input):
    timeframe: Literal["4h", "1d"]
    sma_bars: int = Field(gt=0)


class VolatilityInput(_Input):
    window_bars: int | None = Field(default=None, gt=0)


class FailedBreakoutsInput(_Input):
    lookback_bars: int = Field(gt=0)
    confirm_bars: int | None = Field(default=None, gt=0)


class ToolRegistry:
    """Small, per-snapshot read-only registry; schemas intentionally omit as_of."""

    def __init__(self, as_of: datetime, source: CandleSource, config: Settings) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        self.as_of, self.source, self.config, self.calls = as_of, source, config, 0
        self.records: list[dict[str, object]] = []
        self._models = {
            "volume_vs_average": VolumeInput,
            "higher_timeframe_trend": TrendInput,
            "volatility_regime": VolatilityInput,
            "recent_failed_breakouts": FailedBreakoutsInput,
        }

    def schemas(self) -> dict[str, dict[str, object]]:
        return {name: model.model_json_schema() for name, model in self._models.items()}

    def call(self, name: str, args: dict[str, object]) -> dict[str, object]:
        if "as_of" in args:
            raise ToolError("as_of_override_rejected")
        if self.calls >= self.config.agent_tools.max_calls_per_registry:
            raise ToolError("call_budget_exceeded")
        try:
            model = self._models[name].model_validate(args)
        except (KeyError, ValueError) as error:
            raise ToolError("invalid_arguments") from error
        self.calls += 1
        started = time.perf_counter()
        status, output, fetched = "ok", None, 0
        try:
            candles = list(
                self.source.candles(
                    self.as_of,
                    self.config.agent_tools.max_candles_per_call,
                    self.config.strategy.symbol,
                    self.config.strategy.interval,
                )
            )
            fetched = len(candles)
            enforce_as_of(candles, self.as_of, self.config.strategy.interval)
            output = getattr(self, f"_{name}")(candles, model)
            self.records.append(
                {"tool_name": name, "as_of": self.as_of, "args": args, "output": output}
            )
            return output
        except ToolError as error:
            status = error.code
            raise
        finally:
            try:
                logging.getLogger("trader.agent_tools").info(
                    "tool call",
                    extra={
                        "tool": name,
                        "arguments": {**args, "as_of": self.as_of.isoformat()},
                        "status": status,
                        "alarm": "asof_violation" if status == "asof_violation" else None,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                        "candles_fetched": fetched,
                        "data_through": None if output is None else output.get("data_through"),
                        "digest": hashlib.sha256(repr(output).encode()).hexdigest()[:12],
                    },
                )
            except Exception:
                pass

    def _base(self, candles: list[Candle], reason: str | None = None) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "data_through": candles[-1].open_time + interval_delta(self.config.strategy.interval)
            if candles
            else None,
            "reason": reason,
        }

    def _volume_vs_average(self, candles: list[Candle], args: VolumeInput) -> dict[str, object]:
        short, long = (
            args.lookback_bars or self.config.agent_tools.volume_lookback_bars,
            self.config.agent_tools.volume_long_lookback_bars,
        )
        result = self._base(candles)
        if len(candles) <= max(short, long):
            return {
                **result,
                "latest_volume": None,
                "short_ratio": None,
                "long_ratio": None,
                "reason": "insufficient_history",
            }
        latest = candles[-1].volume

        def ratio(n: int):
            mean = sum((c.volume for c in candles[-n - 1 : -1]), Decimal("0")) / n
            return None if mean == 0 else latest / mean

        return {
            **result,
            "latest_volume": latest,
            "short_ratio": ratio(short),
            "long_ratio": ratio(long),
        }

    def _volatility_regime(self, candles: list[Candle], args: VolatilityInput) -> dict[str, object]:
        window = args.window_bars or self.config.agent_tools.volatility_window_bars
        result = self._base(candles)
        atrs = [atr_at(candles, index, self.config.strategy) for index in range(len(candles))]
        values = [value for value in atrs[-window:] if value is not None]
        if len(values) < window or not candles:
            return {
                **result,
                "atr": None,
                "percentile": None,
                "atr_fraction": None,
                "label": None,
                "reason": "insufficient_history",
            }
        atr = values[-1]
        percentile = Decimal(sum(value <= atr for value in values)) / Decimal(len(values))
        return {
            **result,
            "atr": atr,
            "percentile": percentile,
            "atr_fraction": atr / candles[-1].close,
            "label": "low"
            if percentile < Decimal(".25")
            else "high"
            if percentile > Decimal(".75")
            else "normal",
        }

    def _higher_timeframe_trend(self, candles: list[Candle], args: TrendInput) -> dict[str, object]:
        hours = 4 if args.timeframe == "4h" else 24
        buckets: dict[datetime, list[Candle]] = {}
        for candle in candles:
            start = candle.open_time.replace(hour=(candle.open_time.hour // hours) * hours)
            buckets.setdefault(start, []).append(candle)
        bars = []
        for start, values in sorted(buckets.items()):
            values.sort(key=lambda item: item.open_time)
            expected = [start + interval_delta("1h") * index for index in range(hours)]
            if [item.open_time for item in values] != expected:
                continue
            if start + interval_delta("1h") * hours > self.as_of:
                continue
            bars.append(values[-1].close)
        result = self._base(candles)
        if len(bars) < args.sma_bars:
            return {
                **result,
                "fraction": None,
                "slope": None,
                "label": None,
                "bars_used": len(bars),
                "reason": "insufficient_history",
            }
        sma = sum(bars[-args.sma_bars :], Decimal("0")) / args.sma_bars
        fraction = bars[-1] / sma - Decimal("1")
        band = self.config.agent_tools.trend_flat_band
        label = "up" if fraction > band else "down" if fraction < -band else "flat"
        slope = "up" if bars[-1] > bars[-2] else "down" if bars[-1] < bars[-2] else "flat"
        return {
            **result,
            "fraction": fraction,
            "slope": slope,
            "label": label,
            "bars_used": len(bars),
        }

    def _recent_failed_breakouts(
        self, candles: list[Candle], args: FailedBreakoutsInput
    ) -> dict[str, object]:
        confirm = args.confirm_bars or self.config.agent_tools.failed_breakout_confirm_bars
        start = max(0, len(candles) - args.lookback_bars)
        records: list[dict[str, object]] = []
        for index in range(start, len(candles)):
            candidate = evaluate_candle(candles, index, self.config.strategy)
            if candidate is None:
                continue
            following = candles[index + 1 : index + 1 + confirm]
            failed_at = next(
                (
                    offset + 1
                    for offset, candle in enumerate(following)
                    if candle.close < candidate.breakout_level
                ),
                None,
            )
            state = (
                "RESOLVED_FAILED"
                if failed_at
                else "RESOLVED_HELD"
                if len(following) == confirm
                else "UNRESOLVED"
            )
            records.append(
                {
                    "signal_time": candidate.signal_time,
                    "breakout_level": candidate.breakout_level,
                    "class": state,
                    "bars_to_failure": failed_at,
                }
            )
        failed = sum(record["class"] == "RESOLVED_FAILED" for record in records)
        held = sum(record["class"] == "RESOLVED_HELD" for record in records)
        unresolved = sum(record["class"] == "UNRESOLVED" for record in records)
        resolved = failed + held
        return {
            **self._base(candles),
            "failed": failed,
            "held": held,
            "unresolved": unresolved,
            "failure_fraction": None if not resolved else Decimal(failed) / Decimal(resolved),
            "breakouts": records[-5:],
        }
