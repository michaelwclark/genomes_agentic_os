DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='fabric_tasks' AND column_name='config_fingerprint'
  ) AND (
    EXISTS (
      SELECT 1 FROM fabric_tasks WHERE status IN ('queued','running')
    ) OR EXISTS (
      SELECT 1 FROM fabric_workers WHERE lease_expires_at > now()
    )
  ) THEN
    RAISE EXCEPTION
      'policy enforcement migration requires drained tasks and workers';
  END IF;
END $$;

ALTER TABLE fabric_state
  ADD COLUMN IF NOT EXISTS policy_fingerprint text;

ALTER TABLE fabric_state
  DROP CONSTRAINT IF EXISTS fabric_state_policy_fingerprint_check,
  ADD CONSTRAINT fabric_state_policy_fingerprint_check CHECK (
    policy_fingerprint IS NULL OR policy_fingerprint ~ '^[0-9a-f]{64}$'
  );

ALTER TABLE fabric_tasks
  ADD COLUMN IF NOT EXISTS provider text NOT NULL DEFAULT 'unknown',
  ADD COLUMN IF NOT EXISTS retry_backoff_seconds integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS config_fingerprint text NOT NULL
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';

ALTER TABLE fabric_tasks
  DROP CONSTRAINT IF EXISTS fabric_tasks_retry_backoff_seconds_check,
  ADD CONSTRAINT fabric_tasks_retry_backoff_seconds_check
    CHECK (retry_backoff_seconds >= 0),
  DROP CONSTRAINT IF EXISTS fabric_tasks_config_fingerprint_check,
  ADD CONSTRAINT fabric_tasks_config_fingerprint_check
    CHECK (config_fingerprint ~ '^[0-9a-f]{64}$');

ALTER TABLE fabric_tasks
  ALTER COLUMN provider DROP DEFAULT,
  ALTER COLUMN config_fingerprint DROP DEFAULT;

ALTER TABLE fabric_workers
  ADD COLUMN IF NOT EXISTS pool_id text NOT NULL DEFAULT 'legacy',
  ADD COLUMN IF NOT EXISTS provider text NOT NULL DEFAULT 'unknown',
  ADD COLUMN IF NOT EXISTS config_fingerprint text NOT NULL
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';

ALTER TABLE fabric_workers
  DROP CONSTRAINT IF EXISTS fabric_workers_config_fingerprint_check,
  ADD CONSTRAINT fabric_workers_config_fingerprint_check
    CHECK (config_fingerprint ~ '^[0-9a-f]{64}$');

ALTER TABLE fabric_workers
  ALTER COLUMN pool_id DROP DEFAULT,
  ALTER COLUMN provider DROP DEFAULT,
  ALTER COLUMN config_fingerprint DROP DEFAULT;

CREATE INDEX IF NOT EXISTS fabric_workers_pool_live_idx
  ON fabric_workers(pool_id,lease_expires_at);

ALTER TABLE fabric_attempts
  ADD COLUMN IF NOT EXISTS lease_duration_seconds integer NOT NULL DEFAULT 120;

ALTER TABLE fabric_attempts
  DROP CONSTRAINT IF EXISTS fabric_attempts_lease_duration_seconds_check,
  ADD CONSTRAINT fabric_attempts_lease_duration_seconds_check
    CHECK (lease_duration_seconds >= 30);

ALTER TABLE fabric_attempts
  ALTER COLUMN lease_duration_seconds DROP DEFAULT;
