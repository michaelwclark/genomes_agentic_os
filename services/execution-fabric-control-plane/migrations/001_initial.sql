CREATE TABLE IF NOT EXISTS fabric_state (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  current_epoch bigint NOT NULL DEFAULT 1 CHECK (current_epoch >= 1),
  leader_host_id text,
  leader_lease_expires_at timestamptz,
  policy_fingerprint text CHECK (
    policy_fingerprint IS NULL OR policy_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO fabric_state (singleton) VALUES (true) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS fabric_tasks (
  id uuid PRIMARY KEY,
  namespace text NOT NULL,
  queue_name text NOT NULL,
  task_type text NOT NULL,
  idempotency_key text NOT NULL,
  request_hash text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  required_capabilities jsonb NOT NULL DEFAULT '[]'::jsonb,
  priority integer NOT NULL DEFAULT 0,
  status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','dead_lettered','cancelled')),
  max_attempts integer NOT NULL CHECK (max_attempts BETWEEN 1 AND 100),
  provider text NOT NULL,
  retry_backoff_seconds integer NOT NULL DEFAULT 0
    CHECK (retry_backoff_seconds >= 0),
  config_fingerprint text NOT NULL CHECK (config_fingerprint ~ '^[0-9a-f]{64}$'),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  delivery_published_at timestamptz,
  result jsonb,
  last_error_code text,
  last_error_summary text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  UNIQUE(namespace, idempotency_key)
);
CREATE INDEX IF NOT EXISTS fabric_tasks_claim_idx
  ON fabric_tasks(queue_name, status, available_at, priority DESC, created_at, id);

CREATE TABLE IF NOT EXISTS fabric_runs (
  id uuid PRIMARY KEY,
  task_id uuid NOT NULL REFERENCES fabric_tasks(id),
  run_number integer NOT NULL CHECK (run_number >= 1),
  status text NOT NULL CHECK (status IN ('running','succeeded','failed','expired')),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE(task_id, run_number)
);

CREATE TABLE IF NOT EXISTS fabric_workers (
  worker_id text PRIMARY KEY,
  host_id text NOT NULL,
  pool_id text NOT NULL,
  provider text NOT NULL,
  queues jsonb NOT NULL,
  capabilities jsonb NOT NULL,
  max_concurrency integer NOT NULL CHECK (max_concurrency BETWEEN 1 AND 256),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  registration_token uuid NOT NULL,
  registered_epoch bigint NOT NULL,
  config_fingerprint text NOT NULL CHECK (config_fingerprint ~ '^[0-9a-f]{64}$'),
  lease_expires_at timestamptz NOT NULL,
  last_heartbeat_at timestamptz NOT NULL DEFAULT now(),
  registered_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fabric_workers_live_idx ON fabric_workers(lease_expires_at);
CREATE INDEX IF NOT EXISTS fabric_workers_pool_live_idx
  ON fabric_workers(pool_id,lease_expires_at);

CREATE TABLE IF NOT EXISTS fabric_attempts (
  id uuid PRIMARY KEY,
  task_id uuid NOT NULL REFERENCES fabric_tasks(id),
  run_id uuid NOT NULL REFERENCES fabric_runs(id),
  worker_id text NOT NULL REFERENCES fabric_workers(worker_id),
  attempt_number integer NOT NULL CHECK (attempt_number >= 1),
  status text NOT NULL CHECK (status IN ('running','succeeded','failed','expired','fenced')),
  lease_token uuid NOT NULL,
  fabric_epoch bigint NOT NULL,
  lease_duration_seconds integer NOT NULL
    CHECK (lease_duration_seconds >= 30),
  lease_expires_at timestamptz NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error_code text,
  error_summary text,
  UNIQUE(task_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS fabric_attempts_expiry_idx
  ON fabric_attempts(status, lease_expires_at, task_id);

CREATE TABLE IF NOT EXISTS fabric_events (
  sequence bigserial PRIMARY KEY,
  event_id uuid NOT NULL UNIQUE,
  aggregate_type text NOT NULL,
  aggregate_id text NOT NULL,
  event_type text NOT NULL,
  fabric_epoch bigint NOT NULL,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fabric_events_aggregate_idx
  ON fabric_events(aggregate_type, aggregate_id, sequence);

CREATE TABLE IF NOT EXISTS fabric_effect_outbox (
  id uuid PRIMARY KEY,
  effect_key text NOT NULL UNIQUE,
  task_id uuid NOT NULL REFERENCES fabric_tasks(id),
  attempt_id uuid NOT NULL REFERENCES fabric_attempts(id),
  effect_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  fabric_epoch bigint NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','delivered','failed')),
  available_at timestamptz NOT NULL DEFAULT now(),
  claimed_by text,
  claim_token uuid,
  claimed_at timestamptz,
  claim_expires_at timestamptz,
  delivered_at timestamptz,
  provider_receipt jsonb,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fabric_effect_outbox_delivery_idx
  ON fabric_effect_outbox(status, available_at, created_at);

CREATE TABLE IF NOT EXISTS fabric_schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);
