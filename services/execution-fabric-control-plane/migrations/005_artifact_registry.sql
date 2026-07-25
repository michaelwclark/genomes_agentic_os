CREATE TABLE IF NOT EXISTS fabric_artifacts (
  id uuid PRIMARY KEY,
  task_id uuid NOT NULL REFERENCES fabric_tasks(id),
  attempt_id uuid NOT NULL REFERENCES fabric_attempts(id),
  object_key text NOT NULL UNIQUE,
  name text NOT NULL,
  content_type text NOT NULL,
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 104857600),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','available','failed','expired')),
  storage_uri text,
  etag text,
  upload_expires_at timestamptz NOT NULL,
  available_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(attempt_id, name, sha256)
);
CREATE INDEX IF NOT EXISTS fabric_artifacts_task_idx
  ON fabric_artifacts(task_id, created_at, id);
CREATE INDEX IF NOT EXISTS fabric_artifacts_status_idx
  ON fabric_artifacts(status, upload_expires_at, created_at);
