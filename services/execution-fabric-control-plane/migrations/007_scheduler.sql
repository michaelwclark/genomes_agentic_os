CREATE TABLE IF NOT EXISTS fabric_schedules (
  id text PRIMARY KEY,
  namespace text NOT NULL,
  queue_name text NOT NULL,
  task_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  required_capabilities jsonb NOT NULL DEFAULT '[]'::jsonb,
  priority integer NOT NULL DEFAULT 0 CHECK (priority BETWEEN -1000 AND 1000),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 100),
  interval_seconds integer NOT NULL CHECK (interval_seconds BETWEEN 1 AND 31536000),
  enabled boolean NOT NULL DEFAULT true,
  next_occurrence_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fabric_schedules_due_idx
  ON fabric_schedules(enabled,next_occurrence_at,id);

CREATE TABLE IF NOT EXISTS fabric_schedule_occurrences (
  id uuid PRIMARY KEY,
  schedule_id text NOT NULL REFERENCES fabric_schedules(id),
  scheduled_for timestamptz NOT NULL,
  idempotency_key text NOT NULL,
  fabric_epoch bigint NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processing','admitted','failed','fenced')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 100),
  available_at timestamptz NOT NULL DEFAULT now(),
  claim_token uuid,
  claim_expires_at timestamptz,
  task_id uuid REFERENCES fabric_tasks(id),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(schedule_id,scheduled_for,fabric_epoch),
  UNIQUE(idempotency_key,fabric_epoch)
);
CREATE INDEX IF NOT EXISTS fabric_schedule_occurrences_claim_idx
  ON fabric_schedule_occurrences(status,available_at,fabric_epoch,scheduled_for,id);
