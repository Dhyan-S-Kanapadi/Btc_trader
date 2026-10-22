"""Pure deterministic embeddings and exact, time-gated memory search."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal

from trader.config import AgentMemorySettings
from trader.models import Candidate, FrozenModel, Snapshot, Trade


class Episode(FrozenModel):
    episode_id: str
    namespace: str
    symbol: str
    interval: str
    candidate_key: str
    candidate_time: datetime
    snapshot_digest: str
    features: tuple[float, float, float, float, float]
    embedding: tuple[float, float, float, float, float]
    embedding_version: str
    net_r: Decimal
    exit_reason: str
    bars_held: int
    known_at: datetime
    synthetic: bool


def _bounds(config: AgentMemorySettings) -> tuple[tuple[float, float], ...]:
    return (
        (config.volume_ratio_lo, config.volume_ratio_hi),
        (config.breakout_strength_lo, config.breakout_strength_hi),
        (config.atr_pct_lo, config.atr_pct_hi),
        (config.range_pct_lo, config.range_pct_hi),
        (config.trend_lo, config.trend_hi),
    )


def embedding_version(config: AgentMemorySettings) -> str:
    payload = json.dumps(_bounds(config), separators=(",", ":"), sort_keys=True)
    return "deterministic_v1-" + hashlib.sha256(payload.encode()).hexdigest()[:12]


def embed_snapshot(snapshot: Snapshot, config: AgentMemorySettings) -> list[float] | None:
    values = (
        snapshot.volume_ratio,
        snapshot.breakout_strength_atr,
        snapshot.atr_pct,
        snapshot.range_24h_pct,
        snapshot.trend_vs_sma,
    )
    if any(value is None for value in values):
        return None
    result = []
    for value, (lo, hi) in zip(values, _bounds(config), strict=True):
        number = float(value)
        result.append((min(max(number, lo), hi) - lo) / (hi - lo))
    return result


class InMemoryMemorySource:
    """Exact reference source used by tests; a future row is a loud invariant failure."""

    def __init__(self, episodes: list[Episode]) -> None:
        self.episodes = list(episodes)

    def search(
        self,
        *,
        as_of: datetime,
        candidate_key: str,
        namespace: str,
        embedding: list[float],
        embedding_version: str,
        k: int,
        max_distance: float,
    ) -> list[dict[str, object]]:
        if as_of.tzinfo is None or as_of.astimezone(UTC) != as_of:
            raise ValueError("as_of must be UTC")
        rows = []
        for episode in self.episodes:
            if episode.namespace != namespace or episode.embedding_version != embedding_version:
                continue
            if episode.candidate_key == candidate_key:
                continue
            if episode.known_at > as_of or episode.candidate_time >= as_of:
                continue
            distance = math.dist(embedding, episode.embedding)
            if distance <= max_distance:
                rows.append(
                    {
                        "episode_id": episode.episode_id,
                        "candidate_time": episode.candidate_time,
                        "known_at": episode.known_at,
                        "distance": distance,
                        "features": list(episode.features),
                        "net_r": episode.net_r,
                        "exit_reason": episode.exit_reason,
                        "bars_held": episode.bars_held,
                    }
                )
        return sorted(
            rows, key=lambda row: (row["distance"], row["candidate_time"], row["episode_id"])
        )[:k]


def record_episode(
    candidate: Candidate,
    snapshot: Snapshot,
    trade: Trade,
    known_at: datetime,
    *,
    namespace: str,
    synthetic: bool,
    config: AgentMemorySettings,
) -> Episode | None:
    """Build one immutable outcome only once the Account A exit is known."""

    vector = embed_snapshot(snapshot, config)
    if vector is None or known_at < candidate.signal_time:
        return None
    initial_risk = trade.qty * (trade.entry_price - trade.initial_stop_price)
    if initial_risk <= 0:
        return None
    features = (
        float(snapshot.volume_ratio),
        float(snapshot.breakout_strength_atr),
        float(snapshot.atr_pct),
        float(snapshot.range_24h_pct),
        float(snapshot.trend_vs_sma),
    )
    return Episode(
        episode_id=f"{namespace}:{candidate.idempotency_key}",
        namespace=namespace,
        symbol=candidate.symbol,
        interval="1h",
        candidate_key=candidate.idempotency_key,
        candidate_time=candidate.signal_time,
        snapshot_digest=hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest(),
        features=features,
        embedding=tuple(vector),
        embedding_version=embedding_version(config),
        net_r=(trade.qty * (trade.exit_price - trade.entry_price) - trade.fees) / initial_risk,
        exit_reason=trade.reason,
        bars_held=max(0, int((trade.exit_time - trade.entry_time).total_seconds() // 3600)),
        known_at=known_at,
        synthetic=synthetic,
    )
