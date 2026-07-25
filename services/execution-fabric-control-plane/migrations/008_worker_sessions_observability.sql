CREATE TABLE IF NOT EXISTS fabric_worker_sessions (
  id uuid PRIMARY KEY,
  worker_id text NOT NULL REFERENCES fabric_workers(worker_id),
  registration_token uuid NOT NULL,
  host_id text NOT NULL,
  pool_id text NOT NULL,
  provider text NOT NULL,
  fabric_epoch bigint NOT NULL,
  config_fingerprint text NOT NULL CHECK (config_fingerprint ~ '^[0-9a-f]{64}$'),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','ended','expired','fenced')),
  started_at timestamptz NOT NULL DEFAULT now(),
  last_heartbeat_at timestamptz NOT NULL DEFAULT now(),
  lease_expires_at timestamptz NOT NULL,
  ended_at timestamptz,
  end_reason text
);
CREATE UNIQUE INDEX IF NOT EXISTS fabric_worker_sessions_active_idx
  ON fabric_worker_sessions(worker_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS fabric_worker_sessions_history_idx
  ON fabric_worker_sessions(worker_id,started_at DESC,id);
CREATE INDEX IF NOT EXISTS fabric_worker_sessions_lease_idx
  ON fabric_worker_sessions(status,lease_expires_at);

ALTER TABLE fabric_workers
  ADD COLUMN IF NOT EXISTS current_session_id uuid
  REFERENCES fabric_worker_sessions(id);

ALTER TABLE fabric_attempts
  ADD COLUMN IF NOT EXISTS worker_session_id uuid
  REFERENCES fabric_worker_sessions(id);

CREATE INDEX IF NOT EXISTS fabric_attempts_worker_session_idx
  ON fabric_attempts(worker_session_id,started_at DESC,id);
