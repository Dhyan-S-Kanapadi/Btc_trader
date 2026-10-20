"""Environment-backed configuration for paper-trading research."""

from decimal import Decimal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrategySettings(BaseModel):
    """Assumed strategy parameters to test, not validated choices."""

    symbol: str = Field("BTCUSDT", description="Assumed market symbol for paper-trading data.")
    interval: str = Field("1h", description="Assumed candle interval.")
    breakout_lookback: int = Field(24, gt=0, description="Assumed breakout lookback in bars.")
    atr_period: int = Field(14, gt=0, description="Assumed ATR period in bars.")
    trend_sma_period: int = Field(96, gt=0, description="Assumed trend SMA period in bars.")
    initial_stop_atr_mult: Decimal = Field(
        Decimal("1.5"), gt=0, description="Assumed initial stop distance in ATRs."
    )
    trailing_stop_atr_mult: Decimal = Field(
        Decimal("2.0"), gt=0, description="Assumed trailing stop distance in ATRs."
    )
    time_stop_bars: int = Field(48, gt=0, description="Assumed maximum holding period in bars.")


class RiskSettings(BaseModel):
    """Hard paper-trading risk assumptions."""

    risk_per_trade: Decimal = Field(
        Decimal("0.01"), gt=0, le=1, description="Assumed equity fraction risked per trade."
    )
    daily_loss_cap: Decimal = Field(
        Decimal("0.03"), gt=0, le=1, description="Assumed daily equity-loss cap."
    )
    max_drawdown_halt: Decimal = Field(
        Decimal("0.10"), gt=0, le=1, description="Assumed drawdown level that halts entries."
    )
    max_open_positions: int = Field(1, ge=1, description="Assumed maximum simultaneous positions.")


class CostSettings(BaseModel):
    """Execution-cost assumptions for later paper-broker work."""

    fee_bps: Decimal = Field(
        Decimal("10"), ge=0, description="Assumed fee in basis points per side."
    )
    slippage_bps: Decimal = Field(
        Decimal("5"), ge=0, description="Assumed slippage in basis points."
    )


class Settings(BaseSettings):
    """All configuration sourced from environment variables or explicit test inputs."""

    model_config = SettingsConfigDict(env_prefix="TRADER_", env_nested_delimiter="__")

    strategy: StrategySettings = Field(
        default_factory=StrategySettings, description="Strategy assumptions section."
    )
    risk: RiskSettings = Field(
        default_factory=RiskSettings, description="Risk assumptions section."
    )
    costs: CostSettings = Field(
        default_factory=CostSettings, description="Cost assumptions section."
    )
    database_url: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
        description="PostgreSQL connection URL; required only by database commands.",
    )
