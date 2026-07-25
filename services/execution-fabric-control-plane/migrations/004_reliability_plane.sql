ALTER TABLE fabric_effect_outbox
  ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 8,
  ADD COLUMN IF NOT EXISTS base_backoff_seconds integer NOT NULL DEFAULT 60,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancelled_at timestamptz;

ALTER TABLE fabric_effect_outbox
  DROP CONSTRAINT IF EXISTS fabric_effect_outbox_attempt_count_check,
  ADD CONSTRAINT fabric_effect_outbox_attempt_count_check
    CHECK (attempt_count >= 0),
  DROP CONSTRAINT IF EXISTS fabric_effect_outbox_max_attempts_check,
  ADD CONSTRAINT fabric_effect_outbox_max_attempts_check
    CHECK (max_attempts BETWEEN 1 AND 100),
  DROP CONSTRAINT IF EXISTS fabric_effect_outbox_base_backoff_seconds_check,
  ADD CONSTRAINT fabric_effect_outbox_base_backoff_seconds_check
    CHECK (base_backoff_seconds BETWEEN 1 AND 86400),
  DROP CONSTRAINT IF EXISTS fabric_effect_outbox_status_check,
  ADD CONSTRAINT fabric_effect_outbox_status_check
    CHECK (status IN (
      'pending','processing','delivered','failed','dead_lettered','cancelled'
    ));

CREATE OR REPLACE FUNCTION fabric_bound_effect_failure()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  next_attempt integer;
  delay_seconds integer;
BEGIN
  IF OLD.status = 'processing'
     AND NEW.status = 'pending'
     AND NEW.last_error IS DISTINCT FROM OLD.last_error THEN
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

DROP TRIGGER IF EXISTS fabric_effect_failure_bounds
  ON fabric_effect_outbox;
CREATE TRIGGER fabric_effect_failure_bounds
BEFORE UPDATE ON fabric_effect_outbox
FOR EACH ROW EXECUTE FUNCTION fabric_bound_effect_failure();

CREATE INDEX IF NOT EXISTS fabric_effect_outbox_failures_idx
  ON fabric_effect_outbox(status, attempt_count, available_at, updated_at);

CREATE TABLE IF NOT EXISTS fabric_health_findings (
  id uuid PRIMARY KEY,
  fingerprint text NOT NULL UNIQUE,
  schema_version text NOT NULL DEFAULT 'execution-fabric-health-finding/v1',
  revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
  kind text NOT NULL,
  scope_type text NOT NULL,
  scope_id text NOT NULL,
  severity text NOT NULL CHECK (severity IN ('info','warning','critical')),
  status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','acknowledged','resolved','cancelled')),
  summary text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  observed_count integer NOT NULL DEFAULT 1 CHECK (observed_count >= 1),
  first_observed_at timestamptz NOT NULL DEFAULT now(),
  last_observed_at timestamptz NOT NULL DEFAULT now(),
  acknowledged_at timestamptz,
  acknowledged_by text,
  resolved_at timestamptz,
  cancelled_at timestamptz,
  fabric_epoch bigint NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fabric_health_findings_open_idx
  ON fabric_health_findings(status, severity, kind, last_observed_at);

CREATE TABLE IF NOT EXISTS fabric_alarm_outbox (
  id uuid PRIMARY KEY,
  finding_id uuid NOT NULL REFERENCES fabric_health_findings(id),
  incident_key text NOT NULL,
  schema_version text NOT NULL DEFAULT 'execution-fabric-alarm/v1',
  revision integer NOT NULL CHECK (revision >= 1),
  fabric_epoch bigint NOT NULL,
  severity text NOT NULL CHECK (severity IN ('info','warning','critical')),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN (
      'pending','processing','delivered','failed','dead_lettered',
      'acknowledged','cancelled'
    )),
  payload jsonb NOT NULL,
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts integer NOT NULL DEFAULT 8 CHECK (max_attempts BETWEEN 1 AND 100),
  available_at timestamptz NOT NULL DEFAULT now(),
  claimed_by text,
  claim_token uuid,
  claim_expires_at timestamptz,
  last_error text,
  delivered_at timestamptz,
  delivery_receipt jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(incident_key, revision)
);
CREATE INDEX IF NOT EXISTS fabric_alarm_outbox_delivery_idx
  ON fabric_alarm_outbox(status, available_at, severity, created_at);

CREATE TABLE IF NOT EXISTS fabric_repair_receipts (
  id uuid PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  finding_id uuid NOT NULL REFERENCES fabric_health_findings(id),
  finding_revision integer NOT NULL,
  action text NOT NULL,
  status text NOT NULL
    CHECK (status IN ('running','succeeded','failed','skipped','cancelled')),
  actor text NOT NULL,
  fabric_epoch bigint NOT NULL,
  before_verification jsonb NOT NULL DEFAULT '{}'::jsonb,
  after_verification jsonb,
  error_summary text,
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fabric_repair_receipts_budget_idx
  ON fabric_repair_receipts(action, started_at, status);

CREATE TABLE IF NOT EXISTS fabric_operator_receipts (
  id uuid PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  action text NOT NULL,
  target_type text NOT NULL,
  target_id text NOT NULL,
  actor text NOT NULL,
  fabric_epoch bigint NOT NULL,
  status text NOT NULL CHECK (status IN ('succeeded','rejected','failed')),
  before_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  after_state jsonb,
  reason text,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
