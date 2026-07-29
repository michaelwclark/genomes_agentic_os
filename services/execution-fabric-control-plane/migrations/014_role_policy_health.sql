CREATE TABLE IF NOT EXISTS fabric_role_health (
  host_id text NOT NULL,
  role text NOT NULL CHECK (role IN ('observer', 'healer', 'scheduler')),
  instance_id uuid NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  approved_policy_fingerprint text,
  applied_policy_fingerprint text,
  last_successful_tick_at timestamptz,
  last_tick_at timestamptz,
  last_error text,
  consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (host_id, role),
  CHECK (
    approved_policy_fingerprint IS NULL OR
    approved_policy_fingerprint ~ '^[a-f0-9]{64}$'
  ),
  CHECK (
    applied_policy_fingerprint IS NULL OR
    applied_policy_fingerprint ~ '^[a-f0-9]{64}$'
  )
);

CREATE INDEX IF NOT EXISTS fabric_role_health_updated_idx
  ON fabric_role_health(updated_at DESC);
