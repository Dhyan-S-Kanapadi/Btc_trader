"""Read-only FastAPI surface for paper-trading data."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from trader.config import Settings
from trader.db.models import (
    AccountRow,
    ConfigRow,
    DecisionRow,
    EquityPointRow,
    PositionRow,
    RunMetadataRow,
    TradeRow,
)
from trader.logging import configure_logging

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class Meta(BaseModel):
    synthetic: bool = False
    metadata_status: str


class Page(BaseModel):
    limit: int
    offset: int
    returned: int


class Health(BaseModel):
    status: str
    paper_trading: bool = True


class Account(BaseModel):
    account_id: str
    label: str | None
    policy_name: str | None
    starting_equity: Decimal | None
    enabled: bool
    halted: bool
    halt_reason: str | None
    latest_equity: Decimal
    open_position: bool


class AccountsResponse(BaseModel):
    items: list[Account]
    meta: Meta


class Position(BaseModel):
    account_id: str
    symbol: str
    qty: Decimal
    entry_price: Decimal
    entry_time: datetime
    stop_price: Decimal
    initial_stop_price: Decimal | None


class PositionsResponse(BaseModel):
    items: list[Position]
    meta: Meta


class Trade(BaseModel):
    account_id: str
    symbol: str
    qty: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_time: datetime
    exit_time: datetime
    fees: Decimal
    net_pnl: Decimal
    reason: str


class TradesResponse(BaseModel):
    items: list[Trade]
    page: Page
    meta: Meta


class Equity(BaseModel):
    account_id: str
    recorded_at: datetime
    equity: Decimal


class EquityResponse(BaseModel):
    items: list[Equity]
    page: Page
    meta: Meta


class Pnl(BaseModel):
    account_id: str
    total_pnl: Decimal
    total_return: Decimal | None
    daily_pnl: dict[str, Decimal]
    daily_realized_net_pnl: dict[str, Decimal]


class PnlResponse(BaseModel):
    items: list[Pnl]
    meta: Meta


class Risk(BaseModel):
    account_id: str
    risk_per_trade: Decimal | None
    daily_loss_cap: Decimal | None
    max_drawdown_halt: Decimal | None
    max_open_positions: int | None
    current_drawdown: Decimal
    today_loss: Decimal
    open_positions: int
    halted: bool
    halt_reason: str | None


class RiskResponse(BaseModel):
    items: list[Risk]
    meta: Meta


class Decision(BaseModel):
    account_id: str
    candidate_idempotency_key: str
    action: str
    reason: str
    risk_result: str | None
    verdict: dict[str, Any] | None
    model_version: str | None
    prompt_version: str | None
    trace_id: str | None
    created_at: datetime


class DecisionsResponse(BaseModel):
    items: list[Decision]
    page: Page
    meta: Meta


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(422, "timestamps must be ISO-8601 UTC")
    return value.astimezone(UTC)


Timestamp = Annotated[datetime | None, Query(description="ISO-8601 UTC timestamp")]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]


class ReadOnlyDatabase:
    """Small query-only boundary; the PostgreSQL role remains the primary guardrail."""

    def __init__(self, url: str) -> None:
        engine = create_engine(url, connect_args={"connect_timeout": 1})

        @event.listens_for(engine, "connect")
        def make_read_only(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("SET default_transaction_read_only = on")
            cursor.close()

        self.engine = engine
        self.sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            yield session

    def meta(self, session: Session) -> Meta:
        kinds = session.scalars(
            select(RunMetadataRow.kind).order_by(RunMetadataRow.started_at.desc())
        ).all()
        return Meta(
            synthetic=any(kind == "SYNTHETIC_REPLAY" for kind in kinds),
            metadata_status="present" if kinds else "missing",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API; fail closed when a distinct read-only URL is absent."""

    settings = settings or Settings()
    if not settings.database_url_readonly:
        raise RuntimeError("DATABASE_URL_READONLY is required for trader api")
    database = ReadOnlyDatabase(settings.database_url_readonly)
    app = FastAPI(title="BTC Agentic Paper-Trader API", version="1")
    origins = [value.strip() for value in settings.api.allowed_origins.split(",") if value.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=[],
        )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        configure_logging().info(
            "api request",
            extra={
                "path": request.url.path,
                "status": response.status_code,
                "latency_seconds": time.perf_counter() - started,
            },
        )
        return response

    @app.get("/health", response_model=Health)
    def health() -> Health:
        try:
            with database.session() as session:
                session.execute(text("SELECT 1"))
        except Exception as error:
            raise HTTPException(503, "database unavailable") from error
        return Health(status="ok")

    @app.get("/v1/accounts", response_model=AccountsResponse)
    def accounts() -> AccountsResponse:
        with database.session() as session:
            configs = {
                row.account_id: row.config for row in session.scalars(select(ConfigRow)).all()
            }
            positions = {
                row.account_id
                for row in session.scalars(
                    select(PositionRow).where(PositionRow.exit_time.is_(None))
                ).all()
            }
            items = []
            for row in session.scalars(select(AccountRow).order_by(AccountRow.account_id)).all():
                config = configs.get(row.account_id, {})
                items.append(
                    Account(
                        account_id=row.account_id,
                        label=config.get("label"),
                        policy_name=config.get("policy_name"),
                        starting_equity=_decimal(config.get("starting_equity")),
                        enabled=bool(config.get("enabled", False)),
                        halted=row.halted,
                        halt_reason=_halt_reason(row.engine_state),
                        latest_equity=row.equity,
                        open_position=row.account_id in positions,
                    )
                )
            return AccountsResponse(items=items, meta=database.meta(session))

    @app.get("/v1/positions", response_model=PositionsResponse)
    def positions(account: str | None = None) -> PositionsResponse:
        with database.session() as session:
            statement = select(PositionRow).where(PositionRow.exit_time.is_(None))
            if account:
                statement = statement.where(PositionRow.account_id == account)
            return PositionsResponse(
                items=[
                    Position.model_validate(row, from_attributes=True)
                    for row in session.scalars(
                        statement.order_by(PositionRow.entry_time.desc())
                    ).all()
                ],
                meta=database.meta(session),
            )

    @app.get("/v1/trades", response_model=TradesResponse)
    def trades(
        account: str | None = None,
        start: Timestamp = None,
        end: Timestamp = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> TradesResponse:
        start, end = _utc(start), _utc(end)
        with database.session() as session:
            statement = select(TradeRow)
            if account:
                statement = statement.where(TradeRow.account_id == account)
            if start:
                statement = statement.where(TradeRow.exit_time >= start)
            if end:
                statement = statement.where(TradeRow.exit_time <= end)
            rows = session.scalars(
                statement.order_by(TradeRow.exit_time.desc(), TradeRow.id)
                .offset(offset)
                .limit(limit)
            ).all()
            items = [
                Trade(
                    account_id=row.account_id,
                    symbol=row.symbol,
                    qty=row.qty,
                    entry_price=row.entry_price,
                    exit_price=row.exit_price,
                    entry_time=row.entry_time,
                    exit_time=row.exit_time,
                    fees=row.fees,
                    net_pnl=row.qty * (row.exit_price - row.entry_price) - row.fees,
                    reason=row.reason,
                )
                for row in rows
            ]
            return TradesResponse(
                items=items,
                page=Page(limit=limit, offset=offset, returned=len(items)),
                meta=database.meta(session),
            )

    @app.get("/v1/equity", response_model=EquityResponse)
    def equity(
        account: str | None = None,
        start: Timestamp = None,
        end: Timestamp = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> EquityResponse:
        start, end = _utc(start), _utc(end)
        with database.session() as session:
            statement = select(EquityPointRow)
            if account:
                statement = statement.where(EquityPointRow.account_id == account)
            if start:
                statement = statement.where(EquityPointRow.recorded_at >= start)
            if end:
                statement = statement.where(EquityPointRow.recorded_at <= end)
            rows = session.scalars(
                statement.order_by(EquityPointRow.recorded_at.desc(), EquityPointRow.id)
                .offset(offset)
                .limit(limit)
            ).all()
            items = [Equity.model_validate(row, from_attributes=True) for row in rows]
            return EquityResponse(
                items=items,
                page=Page(limit=limit, offset=offset, returned=len(items)),
                meta=database.meta(session),
            )

    @app.get("/v1/decisions", response_model=DecisionsResponse)
    def decisions(
        account: str | None = None,
        action: str | None = None,
        start: Timestamp = None,
        end: Timestamp = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> DecisionsResponse:
        start, end = _utc(start), _utc(end)
        with database.session() as session:
            statement = select(DecisionRow)
            if account:
                statement = statement.where(DecisionRow.account_id == account)
            if action:
                statement = statement.where(DecisionRow.action == action)
            if start:
                statement = statement.where(DecisionRow.created_at >= start)
            if end:
                statement = statement.where(DecisionRow.created_at <= end)
            rows = session.scalars(
                statement.order_by(DecisionRow.created_at.desc(), DecisionRow.id)
                .offset(offset)
                .limit(limit)
            ).all()
            items = [
                Decision(
                    account_id=row.account_id,
                    candidate_idempotency_key=row.candidate_idempotency_key,
                    action=row.action,
                    reason=row.reason,
                    risk_result=(row.verdict or {}).get("risk_code"),
                    verdict=row.verdict,
                    model_version=row.model_version,
                    prompt_version=row.prompt_version,
                    trace_id=row.trace_id,
                    created_at=row.created_at,
                )
                for row in rows
            ]
            return DecisionsResponse(
                items=items,
                page=Page(limit=limit, offset=offset, returned=len(items)),
                meta=database.meta(session),
            )

    @app.get("/v1/pnl", response_model=PnlResponse)
    def pnl() -> PnlResponse:
        with database.session() as session:
            items = []
            for account in session.scalars(
                select(AccountRow).order_by(AccountRow.account_id)
            ).all():
                config = (
                    session.scalar(
                        select(ConfigRow.config).where(ConfigRow.account_id == account.account_id)
                    )
                    or {}
                )
                starting = _decimal(config.get("starting_equity")) or account.equity
                points = session.scalars(
                    select(EquityPointRow)
                    .where(EquityPointRow.account_id == account.account_id)
                    .order_by(EquityPointRow.recorded_at)
                ).all()
                daily = _daily(points, starting)
                trades = session.scalars(
                    select(TradeRow).where(TradeRow.account_id == account.account_id)
                ).all()
                realized: dict[str, Decimal] = {}
                for trade in trades:
                    key = trade.exit_time.astimezone(UTC).date().isoformat()
                    realized[key] = (
                        realized.get(key, Decimal("0"))
                        + trade.qty * (trade.exit_price - trade.entry_price)
                        - trade.fees
                    )
                items.append(
                    Pnl(
                        account_id=account.account_id,
                        total_pnl=account.equity - starting,
                        total_return=None if starting == 0 else account.equity / starting - 1,
                        daily_pnl=daily,
                        daily_realized_net_pnl=realized,
                    )
                )
            return PnlResponse(items=items, meta=database.meta(session))

    @app.get("/v1/risk", response_model=RiskResponse)
    def risk() -> RiskResponse:
        with database.session() as session:
            items = []
            for row in session.scalars(select(AccountRow).order_by(AccountRow.account_id)).all():
                config = (
                    session.scalar(
                        select(ConfigRow.config).where(ConfigRow.account_id == row.account_id)
                    )
                    or {}
                )
                rules = config.get("risk", {})
                state = row.engine_state or {}
                account = state.get("risk", {})
                items.append(
                    Risk(
                        account_id=row.account_id,
                        risk_per_trade=_decimal(rules.get("risk_per_trade")),
                        daily_loss_cap=_decimal(rules.get("daily_loss_cap")),
                        max_drawdown_halt=_decimal(rules.get("max_drawdown_halt")),
                        max_open_positions=rules.get("max_open_positions"),
                        current_drawdown=Decimal("0")
                        if row.peak_equity == 0
                        else (row.peak_equity - row.equity) / row.peak_equity,
                        today_loss=Decimal("0")
                        if not account
                        else (_decimal(account.get("day_start_equity")) or row.equity) - row.equity,
                        open_positions=int(account.get("open_position_count", 0)),
                        halted=row.halted,
                        halt_reason=_halt_reason(state),
                    )
                )
            return RiskResponse(items=items, meta=database.meta(session))

    return app


def _decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _halt_reason(state: dict[str, object] | None) -> str | None:
    return "halted" if state and state.get("risk", {}).get("halted") else None


def _daily(points: list[EquityPointRow], starting: Decimal) -> dict[str, Decimal]:
    """Compare each UTC day's final mark to the preceding final mark or starting equity."""

    final: dict[str, Decimal] = {}
    for point in points:
        final[point.recorded_at.astimezone(UTC).date().isoformat()] = point.equity
    result: dict[str, Decimal] = {}
    previous = starting
    for key, value in final.items():
        result[key] = value - previous
        previous = value
    return result


def run_api(settings: Settings) -> int:
    """Run uvicorn with the separate, required read-only URL."""

    import uvicorn

    try:
        app = create_app(settings)
    except RuntimeError as error:
        configure_logging().error(str(error), extra={"command": "api"})
        return 1
    uvicorn.run(app, host=settings.api.host, port=settings.api.port)
    return 0
