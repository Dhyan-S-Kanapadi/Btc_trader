-- Run once against the separate AGENT_MEMORY_DATABASE_URL database as its owner.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS agent_memory;

CREATE TABLE IF NOT EXISTS agent_memory.episodes (
  episode_id text PRIMARY KEY,
  namespace text NOT NULL,
  candidate_key text NOT NULL,
  symbol text NOT NULL,
  interval text NOT NULL,
  candidate_time timestamptz NOT NULL,
  snapshot_digest text NOT NULL,
  features jsonb NOT NULL,
  embedding vector(5) NOT NULL,
  embedding_version text NOT NULL,
  net_r numeric NOT NULL,
  exit_reason text NOT NULL,
  bars_held integer NOT NULL CHECK (bars_held >= 0),
  known_at timestamptz NOT NULL CHECK (known_at >= candidate_time),
  synthetic boolean NOT NULL,
  UNIQUE(namespace, candidate_key)
);

-- Provision these login roles outside CI with passwords from a secret store.
DO $$ BEGIN CREATE ROLE agent_memory_reader NOINHERIT; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE agent_memory_writer NOINHERIT; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
GRANT USAGE ON SCHEMA agent_memory TO agent_memory_reader, agent_memory_writer;
REVOKE ALL ON agent_memory.episodes FROM PUBLIC;
REVOKE ALL ON agent_memory.episodes FROM agent_memory_reader, agent_memory_writer;
GRANT SELECT ON agent_memory.episodes TO agent_memory_reader;
GRANT INSERT ON agent_memory.episodes TO agent_memory_writer;
