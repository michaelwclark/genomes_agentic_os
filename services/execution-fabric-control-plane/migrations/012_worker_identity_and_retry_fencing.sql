ALTER TABLE fabric_workers
  ADD COLUMN IF NOT EXISTS bootstrap_id text;

ALTER TABLE fabric_worker_sessions
  ADD COLUMN IF NOT EXISTS bootstrap_id text;

ALTER TABLE fabric_attempts
  ADD COLUMN IF NOT EXISTS recovery_token uuid;

UPDATE fabric_workers
SET bootstrap_id = COALESCE(bootstrap_id, worker_id)
WHERE bootstrap_id IS NULL;

UPDATE fabric_worker_sessions
SET bootstrap_id = COALESCE(bootstrap_id, worker_id)
WHERE bootstrap_id IS NULL;

UPDATE fabric_attempts
SET recovery_token = gen_random_uuid()
WHERE recovery_token IS NULL;

ALTER TABLE fabric_workers
  ALTER COLUMN bootstrap_id SET NOT NULL;

ALTER TABLE fabric_worker_sessions
  ALTER COLUMN bootstrap_id SET NOT NULL;

ALTER TABLE fabric_attempts
  ALTER COLUMN recovery_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS fabric_workers_bootstrap_identity_idx
  ON fabric_workers(bootstrap_id);

CREATE UNIQUE INDEX IF NOT EXISTS fabric_worker_sessions_bootstrap_active_idx
  ON fabric_worker_sessions(bootstrap_id)
  WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS fabric_attempts_recovery_token_idx
  ON fabric_attempts(recovery_token);

CREATE OR REPLACE FUNCTION fabric_bound_effect_failure()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  next_attempt integer;
  delay_seconds integer;
BEGIN
  -- Every claimed delivery that returns to pending consumes one attempt.
  -- Error text is diagnostic only and must never be a retry counter.
  IF OLD.status = 'processing' AND NEW.status = 'pending' THEN
    next_attempt := OLD.attempt_count + 1;
    NEW.attempt_count := next_attempt;
    NEW.claimed_by := NULL;
    NEW.claim_token := NULL;
    NEW.claimed_at := NULL;
    NEW.claim_expires_at := NULL;
    IF next_attempt >= OLD.max_attempts THEN
      NEW.status := 'dead_lettered';
      NEW.dead_lettered_at := now();
      NEW.available_at := now();
    ELSE
      delay_seconds := LEAST(
        86400,
        OLD.base_backoff_seconds * power(2, LEAST(next_attempt - 1, 10))::integer
      );
      NEW.available_at := GREATEST(
        COALESCE(NEW.available_at, now()),
        now() + (delay_seconds * interval '1 second')
      );
    END IF;
  END IF;
  RETURN NEW;
END
$$;
