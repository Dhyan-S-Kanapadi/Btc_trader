"""Postgres implementation for the separate agent-memory database."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from .core import Episode


def _url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


class PostgresMemorySource:
    """Exact L2 search: no ANN index can weaken the time-gate filter."""

    def __init__(self, database_url: str) -> None:
        self.database_url = _url(database_url)

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
        vector = "[" + ",".join(str(value) for value in embedding) + "]"
        query = """
            SELECT episode_id, candidate_key, candidate_time, known_at,
                   embedding <-> %s::vector AS distance,
                   features, net_r, exit_reason, bars_held
            FROM agent_memory.episodes
            WHERE namespace = %s AND embedding_version = %s
              AND known_at <= %s AND candidate_time < %s AND candidate_key <> %s
              AND embedding <-> %s::vector <= %s
            ORDER BY embedding <-> %s::vector, candidate_time, episode_id
            LIMIT %s
        """
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                query,
                (
                    vector,
                    namespace,
                    embedding_version,
                    as_of,
                    as_of,
                    candidate_key,
                    vector,
                    max_distance,
                    vector,
                    k,
                ),
            ).fetchall()
        return [dict(row) for row in rows]


class PostgresMemoryWriter:
    """Insert-only writer; conflicts make repeated sync runs idempotent."""

    def __init__(self, database_url: str) -> None:
        self.database_url = _url(database_url)

    def insert(self, episodes: Iterable[Episode]) -> int:
        query = """
            INSERT INTO agent_memory.episodes (
              episode_id, namespace, candidate_key, symbol, interval, candidate_time,
              snapshot_digest, features,
              embedding, embedding_version, net_r, exit_reason, bars_held, known_at, synthetic
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (namespace, candidate_key) DO NOTHING
        """
        inserted = 0
        with psycopg.connect(self.database_url) as connection:
            for episode in episodes:
                embedding = "[" + ",".join(str(value) for value in episode.embedding) + "]"
                result = connection.execute(
                    query,
                    (
                        episode.episode_id,
                        episode.namespace,
                        episode.candidate_key,
                        episode.symbol,
                        episode.interval,
                        episode.candidate_time,
                        episode.snapshot_digest,
                        json.dumps(episode.features),
                        embedding,
                        episode.embedding_version,
                        episode.net_r,
                        episode.exit_reason,
                        episode.bars_held,
                        episode.known_at,
                        episode.synthetic,
                    ),
                )
                inserted += result.rowcount
        return inserted
