"""Environment-backed configuration for paper-trading research."""

# ruff: noqa: E501

from decimal import Decimal

from pydantic import BaseModel, Field, model_validator
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
    volume_ratio_min: Decimal = Field(
        Decimal("1.5"), gt=0, description="Assumed minimum volume ratio for replay filtering."
    )


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
    starting_equity: Decimal = Field(
        Decimal("10000"),
        gt=0,
        description="Assumed paper-account starting equity in quote currency.",
    )


class CostSettings(BaseModel):
    """Execution-cost assumptions for later paper-broker work."""

    fee_bps: Decimal = Field(
        Decimal("10"), ge=0, description="Assumed fee in basis points per side."
    )
    slippage_bps: Decimal = Field(
        Decimal("5"), ge=0, description="Assumed slippage in basis points."
    )


class DataSettings(BaseModel):
    """Public market-data ingestion settings; no credentials are used."""

    base_url: str = Field(
        "https://data-api.binance.vision",
        description="Public Binance market-data base URL, without a trailing path.",
    )
    timeout_seconds: float = Field(10.0, gt=0, description="HTTP request timeout in seconds.")
    max_retries: int = Field(
        3, ge=0, le=10, description="Retries for transient public-data failures."
    )
    max_retry_seconds: float = Field(30.0, gt=0, description="Maximum delay for one retry.")
    backfill_days: int = Field(30, gt=0, description="Default number of days for CLI backfill.")


class ReportSettings(BaseModel):
    """Reporting assumptions; this threshold is not a validated statistical rule."""

    report_min_trades: int = Field(
        30, gt=0, description="Assumed minimum closed-trade sample size for a comparison warning."
    )


class WorkerSettings(BaseModel):
    """Paper-worker scheduling and recovery settings."""

    candle_close_buffer_seconds: int = Field(10, ge=0, description="Delay after candle close.")
    poll_retry_seconds: int = Field(30, gt=0, description="Retry delay after a failed cycle.")
    max_cycle_failures: int = Field(3, gt=0, description="Consecutive failures before exit.")
    lock_key: int = Field(13_000_001, description="PostgreSQL advisory-lock key.")


class ApiSettings(BaseModel):
    """Read-only HTTP API settings; credentials never fall back to the writer URL."""

    host: str = "0.0.0.0"
    port: int = Field(8000, ge=1, le=65535)
    allowed_origins: str = ""
    default_limit: int = Field(100, ge=1, le=500)
    max_limit: int = Field(500, ge=1, le=500)


class AgentToolsSettings(BaseModel):
    """Read-only evidence-tool assumptions; none are trading or model controls."""

    api_base_url: str = "http://localhost:8000"
    timeout_seconds: float = Field(5, gt=0)
    max_retries: int = Field(1, ge=0, le=3)
    max_candles_per_call: int = Field(1000, ge=1, le=5000)
    max_calls_per_registry: int = Field(20, ge=1, le=100)
    volume_lookback_bars: int = Field(24, gt=0)
    volume_long_lookback_bars: int = Field(168, gt=0)
    volatility_window_bars: int = Field(720, gt=0)
    failed_breakout_confirm_bars: int = Field(6, gt=0)
    trend_flat_band: Decimal = Field(Decimal("0.001"), ge=0)


class GuardrailSettings(BaseModel):
    """Fail-closed output validation assumptions, not trading parameters."""

    max_raw_bytes: int = Field(4096, gt=0)
    max_depth: int = Field(12, gt=0)
    max_reasons: int = Field(5, gt=0)
    max_reason_length: int = Field(240, gt=0)
    max_reason_total: int = Field(800, gt=0)
    min_citations: int = Field(1, gt=0)
    min_citations_take: int = Field(2, gt=0)
    max_citations: int = Field(12, gt=0)


class NewsSettings(BaseModel):
    """Forward-test BLS schedule bounds; each default is an operational assumption."""

    sources: str = "bls"
    poll_interval_seconds: int = Field(300, gt=0)
    total_deadline_seconds: float = Field(10, gt=0)
    max_retries: int = Field(2, ge=0, le=5)
    max_retry_seconds: float = Field(30, gt=0)
    breaker_failure_threshold: int = Field(3, ge=1)
    breaker_cooldown_seconds: float = Field(300, gt=0)
    max_items_per_poll: int = Field(100, gt=0, le=1000)
    max_response_bytes: int = Field(1_000_000, gt=0)
    redirect_limit: int = Field(2, ge=0, le=5)
    skew_seconds: int = Field(300, ge=0)
    max_timestamp_age_seconds: int = Field(31_536_000, gt=0)
    max_poll_staleness_seconds: int = Field(900, gt=0)
    near_duplicate_window_seconds: int = Field(86_400, gt=0)
    text_cap: int = Field(200, gt=1, le=1000)
    lock_key: int = Field(25_000_001)


class JevSettings(BaseModel):
    """Forward-test sensor bounds; all defaults are operational assumptions."""

    enabled: bool = False
    gateway_token: str | None = Field(default=None, exclude=True, repr=False)
    base_url: str = "https://ai-gateway.vercel.sh"
    model: str = "typesafe-ai/jev-1.14.0"
    total_deadline_seconds: float = Field(10, gt=0, le=60)
    connect_timeout_seconds: float = Field(2, gt=0, le=30)
    max_retries: int = Field(1, ge=0, le=3)
    max_retry_seconds: float = Field(5, gt=0, le=30)
    breaker_failure_threshold: int = Field(3, ge=1)
    breaker_cooldown_seconds: float = Field(300, gt=0)
    window_hours: int = Field(4, gt=0, le=24)
    max_headlines: int = Field(20, gt=0, le=100)
    max_state_characters: int = Field(4000, gt=0, le=16000)
    max_response_bytes: int = Field(65536, gt=0)
    daily_call_cap: int = Field(24, ge=0)
    daily_cost_cap_usd: Decimal | None = Field(default=Decimal("0.01"), ge=0)
    price_per_million_input_usd: Decimal | None = Field(default=Decimal("0.04"), ge=0)
    calibration_k: Decimal = Field(Decimal("2"), gt=0)
    calibration_min_n: int = Field(100, gt=0)


class AgentSettings(BaseModel):
    """Pinned investigator plumbing caps; these do not grant trading authority."""

    model_id: str | None = None
    prompt_version: str = "investigator_v1"
    step_cap: int = Field(3, gt=0)
    max_tokens_per_call: int = Field(512, gt=0)
    max_total_tokens: int = Field(1024, gt=0)
    wall_clock_seconds: float = Field(15, gt=0)
    checkpoint_database_url: str | None = Field(
        default=None, validation_alias="AGENT_CHECKPOINT_DATABASE_URL"
    )
    groq_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = Field(10, gt=0, le=60)


class AgentTracingSettings(BaseModel):
    """Opt-in agent-only observation settings; defaults are operational assumptions."""

    enabled: bool = False
    project_name: str = "btc-paper-agent-live"
    endpoint: str = "https://api.smith.langchain.com"
    timeout_seconds: float = Field(2, gt=0, le=10)
    max_retries: int = Field(0, ge=0, le=1)
    payload_cap: int = Field(8192, ge=256, le=65536)
    flush_timeout_seconds: float = Field(2, gt=0, le=10)
    dataset_prefix: str = "btc-paper-agent-failures"


class AgentMemorySettings(BaseModel):
    """Fixed local embeddings and exact retrieval; every default is an assumption."""

    enabled: bool = False
    database_url: str | None = Field(default=None, validation_alias="AGENT_MEMORY_DATABASE_URL")
    write_database_url: str | None = Field(
        default=None, validation_alias="AGENT_MEMORY_WRITE_DATABASE_URL"
    )
    namespace: str = "live"
    embedder: str = Field("deterministic_v1", pattern="^deterministic_v1$")
    k_cap: int = Field(5, ge=1, le=20)
    max_distance: float = Field(2.0, gt=0)
    min_sample: int = Field(3, ge=1)
    volume_ratio_lo: float = 0.0
    volume_ratio_hi: float = 5.0
    breakout_strength_lo: float = -2.0
    breakout_strength_hi: float = 5.0
    atr_pct_lo: float = 0.0
    atr_pct_hi: float = 0.2
    range_pct_lo: float = 0.0
    range_pct_hi: float = 0.5
    trend_lo: float = -0.2
    trend_hi: float = 0.2


class AgentClientSettings(BaseModel):
    """Worker-side safety bounds; defaults are conservative operational assumptions."""

    target: str = Field("local", pattern="^(local|http|agentcore)$")
    service_url: str | None = None
    service_token: str | None = Field(default=None, validation_alias="AGENT_SERVICE_TOKEN")
    total_deadline_seconds: float = Field(10, gt=0, le=60)
    connect_timeout_seconds: float = Field(2, gt=0, le=30)
    max_retries: int = Field(1, ge=0, le=1)
    breaker_failure_threshold: int = Field(3, ge=1)
    breaker_cooldown_seconds: float = Field(300, gt=0)
    cycle_budget_seconds: float = Field(20, gt=0)


class Settings(BaseSettings):
    """All configuration sourced from environment variables or explicit test inputs."""

    model_config = SettingsConfigDict(
        env_prefix="TRADER_", env_nested_delimiter="__", env_file=".env"
    )

    strategy: StrategySettings = Field(
        default_factory=StrategySettings, description="Strategy assumptions section."
    )
    risk: RiskSettings = Field(
        default_factory=RiskSettings, description="Risk assumptions section."
    )
    costs: CostSettings = Field(
        default_factory=CostSettings, description="Cost assumptions section."
    )
    data: DataSettings = Field(
        default_factory=DataSettings, description="Public market-data section."
    )
    report: ReportSettings = Field(
        default_factory=ReportSettings, description="Report assumptions section."
    )
    worker: WorkerSettings = Field(
        default_factory=WorkerSettings, description="Worker settings section."
    )
    api: ApiSettings = Field(
        default_factory=ApiSettings, description="Read-only API settings section."
    )
    agent_tools: AgentToolsSettings = Field(default_factory=AgentToolsSettings)
    guardrail: GuardrailSettings = Field(default_factory=GuardrailSettings)
    news: NewsSettings = Field(default_factory=NewsSettings)
    jev: JevSettings = Field(default_factory=JevSettings)
    gateway_token: str | None = Field(
        default=None, validation_alias="AI_GATEWAY_API_KEY", exclude=True, repr=False
    )
    groq_token: str | None = Field(
        default=None, validation_alias="GROQ_API_KEY", exclude=True, repr=False
    )
    agent: AgentSettings = Field(default_factory=AgentSettings)
    agent_tracing: AgentTracingSettings = Field(default_factory=AgentTracingSettings)
    agent_memory: AgentMemorySettings = Field(default_factory=AgentMemorySettings)
    agent_memory_database_url: str | None = Field(
        default=None,
        validation_alias="AGENT_MEMORY_DATABASE_URL",
        exclude=True,
        repr=False,
    )
    agent_memory_write_database_url: str | None = Field(
        default=None,
        validation_alias="AGENT_MEMORY_WRITE_DATABASE_URL",
        exclude=True,
        repr=False,
    )
    agent_client: AgentClientSettings = Field(default_factory=AgentClientSettings)
    database_url: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
        description="PostgreSQL connection URL; required only by database commands.",
    )
    database_url_readonly: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL_READONLY",
        description="PostgreSQL read-only API connection URL; never falls back to DATABASE_URL.",
    )

    @model_validator(mode="after")
    def apply_agent_memory_database_url(self) -> "Settings":
        """Keep the separate-memory URL out of nested config names and logs."""

        if (
            self.agent_memory_database_url is not None
            or self.agent_memory_write_database_url is not None
        ):
            self.agent_memory = self.agent_memory.model_copy(
                update={
                    "database_url": self.agent_memory_database_url,
                    "write_database_url": self.agent_memory_write_database_url,
                }
            )
        if self.gateway_token is not None:
            self.jev = self.jev.model_copy(update={"gateway_token": self.gateway_token})
        return self
