"""Validated, immutable data structures shared by later paper-trading work."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenModel(BaseModel):
    """Reject unknown fields and prevent attribute reassignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("datetime must be timezone-aware UTC")
    return value.astimezone(UTC)


class Candle(FrozenModel):
    """One closed market-data candle."""

    symbol: str = Field(min_length=1)
    open_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)

    _validate_open_time = field_validator("open_time")(_utc_datetime)

    @model_validator(mode="after")
    def validate_range(self) -> "Candle":
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("candle range must contain open and close")
        return self


class Candidate(FrozenModel):
    """A deterministic signal candidate at a particular bar."""

    symbol: str = Field(min_length=1)
    bar_index: int = Field(ge=0)
    signal_time: datetime
    reference_price: Decimal = Field(gt=0)
    atr: Decimal = Field(gt=0)
    breakout_level: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=1)

    _validate_signal_time = field_validator("signal_time")(_utc_datetime)


class Snapshot(FrozenModel):
    """Version-1 agent evidence: fractions are ratios (0.01 is 1%), never percent numbers.

    `volume_ratio` uses prior-lookback volume, `breakout_strength_atr` is breakout distance in
    ATR units, `atr_pct` is ATR/reference price, `range_24h_pct` is inclusive-window range/reference
    price, and `trend_vs_sma` is reference price/SMA minus one.
    """

    schema_version: Literal[1] = 1
    idempotency_key: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    signal_time: datetime
    reference_price: Decimal = Field(gt=0)
    atr: Decimal = Field(gt=0)
    breakout_level: Decimal = Field(gt=0)
    volume_ratio: Decimal | None = None
    breakout_strength_atr: Decimal | None = None
    atr_pct: Decimal | None = None
    range_24h_pct: Decimal | None = None
    trend_vs_sma: Decimal | None = None

    _validate_signal_time = field_validator("signal_time")(_utc_datetime)


class Verdict(FrozenModel):
    """An agent verdict that cannot include sizing, stop, or risk instructions."""

    action: Literal["TAKE", "SKIP", "WAIT"]
    reasons: list[str]
    cited_evidence: dict[str, Decimal | str | int | float | bool | None]


class Position(FrozenModel):
    """Minimal long-only spot position state."""

    account_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    qty: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    entry_time: datetime
    stop_price: Decimal = Field(gt=0)
    exit_price: Decimal | None = Field(default=None, gt=0)
    exit_time: datetime | None = None
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    reason: str = Field(min_length=1)
    entry_fee: Decimal = Field(default=Decimal("0"), ge=0)
    highest_high_since_entry: Decimal | None = Field(default=None, gt=0)
    bars_held: int = Field(default=0, ge=0)
    time_stop_exit_due: bool = False

    _validate_entry_time = field_validator("entry_time")(_utc_datetime)

    @field_validator("exit_time")
    @classmethod
    def validate_exit_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc_datetime(value)


class Trade(FrozenModel):
    """Minimal completed long-only spot trade."""

    account_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    qty: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    entry_time: datetime
    stop_price: Decimal = Field(gt=0)
    exit_price: Decimal = Field(gt=0)
    exit_time: datetime
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    reason: str = Field(min_length=1)

    _validate_entry_time = field_validator("entry_time")(_utc_datetime)
    _validate_exit_time = field_validator("exit_time")(_utc_datetime)
