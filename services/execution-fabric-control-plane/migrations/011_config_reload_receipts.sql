CREATE TABLE IF NOT EXISTS fabric_config_reload_receipts (
  id uuid PRIMARY KEY,
  schema_version text NOT NULL DEFAULT 'execution-fabric-config-reload-receipt/v1',
  expected_current_fingerprint text NOT NULL
    CHECK (expected_current_fingerprint ~ '^[a-f0-9]{64}$'),
  expected_candidate_fingerprint text NOT NULL
    CHECK (expected_candidate_fingerprint ~ '^[a-f0-9]{64}$'),
  applied_fingerprint text NOT NULL
    CHECK (applied_fingerprint ~ '^[a-f0-9]{64}$'),
  fabric_epoch bigint NOT NULL,
  host_id text NOT NULL,
  applied_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fabric_config_reload_receipts_recent_idx
  ON fabric_config_reload_receipts(applied_at DESC);
