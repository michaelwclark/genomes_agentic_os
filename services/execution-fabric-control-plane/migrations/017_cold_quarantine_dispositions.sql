-- Preserve migration016 evidence. Legacy readers keep the same names and see
-- active holds; legacy INSERT ... ON CONFLICT writers fail closed on the views.
ALTER TABLE fabric_cold_task_quarantine RENAME TO fabric_cold_task_quarantine_history;
ALTER TABLE fabric_cold_task_quarantine_history DROP CONSTRAINT fabric_cold_task_quarantine_pkey;
ALTER TABLE fabric_cold_task_quarantine_history ADD PRIMARY KEY (recovery_id, task_id);
ALTER TABLE fabric_cold_effect_quarantine RENAME TO fabric_cold_effect_quarantine_history;
ALTER TABLE fabric_cold_effect_quarantine_history DROP CONSTRAINT fabric_cold_effect_quarantine_pkey;
ALTER TABLE fabric_cold_effect_quarantine_history ADD PRIMARY KEY (recovery_id, effect_id);
ALTER TABLE fabric_cold_alarm_quarantine RENAME TO fabric_cold_alarm_quarantine_history;
ALTER TABLE fabric_cold_alarm_quarantine_history DROP CONSTRAINT fabric_cold_alarm_quarantine_pkey;
ALTER TABLE fabric_cold_alarm_quarantine_history ADD PRIMARY KEY (recovery_id, alarm_id);
ALTER TABLE fabric_cold_artifact_quarantine RENAME TO fabric_cold_artifact_quarantine_history;
ALTER TABLE fabric_cold_artifact_quarantine_history DROP CONSTRAINT fabric_cold_artifact_quarantine_pkey;
ALTER TABLE fabric_cold_artifact_quarantine_history ADD PRIMARY KEY (recovery_id, artifact_id);

CREATE TABLE fabric_cold_dispositions (
  sequence bigserial PRIMARY KEY,
  recovery_id uuid NOT NULL REFERENCES fabric_cold_recoveries(recovery_id),
  generation bigint NOT NULL CHECK (generation >= 1),
  fabric_epoch bigint NOT NULL CHECK (fabric_epoch >= 1),
  cluster_id text NOT NULL,
  target_host text NOT NULL,
  pg_system_id text NOT NULL CHECK (pg_system_id ~ '^[0-9]{1,32}$'),
  plan_sha256 text NOT NULL CHECK (plan_sha256 ~ '^[a-f0-9]{64}$'),
  config_fingerprint text NOT NULL CHECK (config_fingerprint ~ '^[a-f0-9]{64}$'),
  accepted_receipt jsonb NOT NULL,
  item_kind text NOT NULL CHECK (item_kind IN ('task', 'effect')),
  item_id uuid NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[a-f0-9]{64}$'),
  predecessor_sha256 text CHECK (predecessor_sha256 ~ '^[a-f0-9]{64}$'),
  disposition text NOT NULL CHECK (disposition IN ('hold', 'task_cancel')),
  releases_quarantine boolean NOT NULL,
  receipt_sha256 text NOT NULL UNIQUE CHECK (receipt_sha256 ~ '^[a-f0-9]{64}$'),
  receipt jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- No genuine positive producer/evidence contract is qualified in this version.
  -- A later release feature requires an explicitly qualified additive migration.
  CHECK (NOT releases_quarantine)
);
-- An append-only chain has one successor, including at its genesis. Concurrent
-- different requests cannot fork it or replace a previous decision.
CREATE UNIQUE INDEX fabric_cold_disposition_successor
  ON fabric_cold_dispositions(recovery_id, item_kind, item_id,
    COALESCE(predecessor_sha256, 'genesis'));
CREATE INDEX fabric_cold_disposition_item
  ON fabric_cold_dispositions(recovery_id, item_kind, item_id, sequence DESC);
CREATE INDEX fabric_cold_task_history_item ON fabric_cold_task_quarantine_history(task_id);
CREATE INDEX fabric_cold_effect_history_item ON fabric_cold_effect_quarantine_history(effect_id);
CREATE INDEX fabric_cold_alarm_history_item ON fabric_cold_alarm_quarantine_history(alarm_id);
CREATE INDEX fabric_cold_artifact_history_item ON fabric_cold_artifact_quarantine_history(artifact_id);

CREATE FUNCTION fabric_preserve_cold_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'cold quarantine and disposition history is immutable';
END;
$$;
CREATE TRIGGER fabric_preserve_cold_task_history BEFORE UPDATE OR DELETE
  ON fabric_cold_task_quarantine_history FOR EACH ROW EXECUTE FUNCTION fabric_preserve_cold_history();
CREATE TRIGGER fabric_preserve_cold_effect_history BEFORE UPDATE OR DELETE
  ON fabric_cold_effect_quarantine_history FOR EACH ROW EXECUTE FUNCTION fabric_preserve_cold_history();
CREATE TRIGGER fabric_preserve_cold_alarm_history BEFORE UPDATE OR DELETE
  ON fabric_cold_alarm_quarantine_history FOR EACH ROW EXECUTE FUNCTION fabric_preserve_cold_history();
CREATE TRIGGER fabric_preserve_cold_artifact_history BEFORE UPDATE OR DELETE
  ON fabric_cold_artifact_quarantine_history FOR EACH ROW EXECUTE FUNCTION fabric_preserve_cold_history();
CREATE TRIGGER fabric_preserve_cold_dispositions BEFORE UPDATE OR DELETE
  ON fabric_cold_dispositions FOR EACH ROW EXECUTE FUNCTION fabric_preserve_cold_history();

-- Latest hold per item, with a release recognized only by the current accepted
-- recovery and epoch. Older receipts remain history during later failback.
CREATE VIEW fabric_cold_task_quarantine AS
SELECT q.* FROM fabric_cold_task_quarantine_history q
JOIN fabric_cold_recoveries r ON r.recovery_id = q.recovery_id
WHERE NOT EXISTS (
  SELECT 1 FROM fabric_cold_task_quarantine_history newer
  JOIN fabric_cold_recoveries nr ON nr.recovery_id = newer.recovery_id
  WHERE newer.task_id = q.task_id AND nr.generation > r.generation
) AND NOT EXISTS (
  SELECT 1 FROM fabric_cold_dispositions d JOIN fabric_state s ON s.singleton
  WHERE d.recovery_id = q.recovery_id AND d.item_kind = 'task' AND d.item_id = q.task_id
    AND d.releases_quarantine AND s.cold_recovery_phase = 'ACCEPTED'
    AND s.cold_recovery_id = d.recovery_id AND s.cold_recovery_generation = d.generation
    AND s.current_epoch = d.fabric_epoch AND r.generation = d.generation
    AND s.leadership_cluster_id = d.cluster_id AND s.leader_host_id = d.target_host
    AND s.policy_fingerprint = d.config_fingerprint AND r.phase = 'ACCEPTED'
    AND r.plan_sha256 = d.plan_sha256 AND r.plan->>'newPgSystemId' = d.pg_system_id
    AND r.receipts->'accept' = d.accepted_receipt
    AND NOT EXISTS (SELECT 1 FROM fabric_cold_dispositions later
      WHERE later.recovery_id = d.recovery_id AND later.item_kind = d.item_kind
        AND later.item_id = d.item_id AND later.sequence > d.sequence)
);
-- No provider outcome verifier is admitted in this revision. Every effect,
-- alarm and artifact remains held; a generic provider receipt cannot release it.
CREATE VIEW fabric_cold_effect_quarantine AS
SELECT q.* FROM fabric_cold_effect_quarantine_history q
JOIN fabric_cold_recoveries r ON r.recovery_id = q.recovery_id
WHERE NOT EXISTS (
  SELECT 1 FROM fabric_cold_effect_quarantine_history newer
  JOIN fabric_cold_recoveries nr ON nr.recovery_id = newer.recovery_id
  WHERE newer.effect_id = q.effect_id AND nr.generation > r.generation
);
CREATE VIEW fabric_cold_alarm_quarantine AS
SELECT q.* FROM fabric_cold_alarm_quarantine_history q
JOIN fabric_cold_recoveries r ON r.recovery_id = q.recovery_id
WHERE NOT EXISTS (
  SELECT 1 FROM fabric_cold_alarm_quarantine_history newer
  JOIN fabric_cold_recoveries nr ON nr.recovery_id = newer.recovery_id
  WHERE newer.alarm_id = q.alarm_id AND nr.generation > r.generation
);
CREATE VIEW fabric_cold_artifact_quarantine AS
SELECT q.* FROM fabric_cold_artifact_quarantine_history q
JOIN fabric_cold_recoveries r ON r.recovery_id = q.recovery_id
WHERE NOT EXISTS (
  SELECT 1 FROM fabric_cold_artifact_quarantine_history newer
  JOIN fabric_cold_recoveries nr ON nr.recovery_id = newer.recovery_id
  WHERE newer.artifact_id = q.artifact_id AND nr.generation > r.generation
);
