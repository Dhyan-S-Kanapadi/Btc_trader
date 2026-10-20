"""One-candle multi-account routing over the shared replay engine."""

import logging
from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import Field

from trader.config import Settings
from trader.models import Candle, FrozenModel
from trader.strategy import build_snapshot, evaluate_candle

from .engine import (
    DecisionPolicy,
    PolicyDecision,
    ReplayState,
    SharedSignal,
    StepResult,
    TakeAllPolicy,
    VolumeFilterPolicy,
    step,
)


class AccountConfig(FrozenModel):
    """Non-secret per-account settings stored in the existing configs JSON document."""

    account_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    policy_name: str = Field(min_length=1)
    starting_equity: Decimal = Field(gt=0)
    enabled: bool = True


class SkipAllPolicy:
    """Temporary B-D baseline until Issue #27 provides real policies."""

    def decide(self, snapshot, candidate) -> PolicyDecision:
        return PolicyDecision(action="SKIP", reason="agent not wired yet (#27)")


def policy_for(name: str, settings: Settings) -> DecisionPolicy:
    """Return a configured policy or fail fast while loading account configuration."""

    policies: dict[str, DecisionPolicy] = {
        "take_all": TakeAllPolicy(),
        "skip_all": SkipAllPolicy(),
        "volume_filter": VolumeFilterPolicy(settings.strategy.volume_ratio_min),
    }
    try:
        return policies[name]
    except KeyError as error:
        raise ValueError(f"unknown paper-account policy: {name}") from error


def route_candle(
    accounts: Mapping[str, tuple[ReplayState, AccountConfig]],
    history: Sequence[Candle],
    candle: Candle,
    settings: Settings,
) -> dict[str, StepResult]:
    """Route one closed candle independently, sharing exactly one candidate and snapshot."""

    candidate = evaluate_candle(history, len(history) - 1, settings.strategy)
    signal = (
        None
        if candidate is None
        else SharedSignal(
            candidate=candidate, snapshot=build_snapshot(history, candidate, settings.strategy)
        )
    )
    results: dict[str, StepResult] = {}
    logger = logging.getLogger("trader.replay.router")
    for account_id, (state, account) in accounts.items():
        if not account.enabled:
            continue
        try:
            results[account_id] = step(
                state, history, candle, policy_for(account.policy_name, settings), settings, signal
            )
        except Exception:
            logger.exception("account routing failed", extra={"account_id": account_id})
    return results
