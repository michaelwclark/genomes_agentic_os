CREATE TABLE IF NOT EXISTS fabric_external_observations (
  source text NOT NULL,
  incident_key text NOT NULL,
  revision integer NOT NULL CHECK (revision >= 1),
  observation jsonb NOT NULL,
  finding_id uuid NOT NULL REFERENCES fabric_health_findings(id),
  received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(source, incident_key, revision)
);

CREATE INDEX IF NOT EXISTS fabric_external_observations_recent_idx
  ON fabric_external_observations(source, received_at DESC);
