ALTER TABLE fabric_external_observations
  ADD COLUMN IF NOT EXISTS active boolean;

UPDATE fabric_external_observations
SET active=COALESCE((observation->>'active')::boolean,true)
WHERE active IS NULL;

ALTER TABLE fabric_external_observations
  ALTER COLUMN active SET DEFAULT true,
  ALTER COLUMN active SET NOT NULL;

ALTER TABLE fabric_alarm_outbox
  DROP CONSTRAINT IF EXISTS fabric_alarm_outbox_status_check;

ALTER TABLE fabric_alarm_outbox
  ADD CONSTRAINT fabric_alarm_outbox_status_check
  CHECK (status IN (
    'pending','processing','delivered','failed','dead_lettered',
    'resolved_awaiting_ack','acknowledged','cancelled'
  ));

CREATE TABLE IF NOT EXISTS fabric_external_recoveries (
  source text NOT NULL,
  incident_key text NOT NULL,
  revision integer NOT NULL CHECK (revision >= 1),
  finding_id uuid NOT NULL REFERENCES fabric_health_findings(id),
  fabric_epoch bigint NOT NULL,
  observation jsonb NOT NULL,
  recovered_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(source,incident_key,revision)
);

CREATE INDEX IF NOT EXISTS fabric_external_recoveries_recent_idx
  ON fabric_external_recoveries(recovered_at DESC);
