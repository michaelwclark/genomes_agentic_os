-- No bootstrap/reseed: the restored authority row must already exist.
ALTER TABLE fabric_state
 ADD COLUMN cold_recovery_id uuid,
 ADD COLUMN cold_recovery_phase text CHECK(cold_recovery_phase IN ('LEDGER_HELD','LEDGER_COMMITTED_HELD','CANARY_ADMITTED','ACCEPTED')),
 ADD COLUMN cold_recovery_generation bigint NOT NULL DEFAULT 0 CHECK(cold_recovery_generation>=0),
 ADD COLUMN cold_canary_task_id uuid,
 ADD COLUMN cold_canary_worker_id text;
CREATE TABLE fabric_cold_recoveries(
 recovery_id uuid PRIMARY KEY,
 plan_sha256 text NOT NULL CHECK(plan_sha256 ~ '^[a-f0-9]{64}$'),
 generation bigint NOT NULL CHECK(generation>=1),
 expected_epoch bigint NOT NULL CHECK(expected_epoch>=1),
 next_epoch bigint NOT NULL CHECK(next_epoch>expected_epoch),
 source_host text NOT NULL,
 target_host text NOT NULL CHECK(target_host<>source_host),
 phase text NOT NULL CHECK(phase IN ('LEDGER_HELD','LEDGER_COMMITTED_HELD','CANARY_ADMITTED','ACCEPTED')),
 plan jsonb NOT NULL,
 receipts jsonb NOT NULL DEFAULT '{}'::jsonb,
 canary_io_baseline_sha256 text CHECK(canary_io_baseline_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(generation)
);
CREATE TABLE fabric_cold_task_quarantine(
 recovery_id uuid NOT NULL REFERENCES fabric_cold_recoveries(recovery_id),
 task_id uuid PRIMARY KEY REFERENCES fabric_tasks(id),
 original_status text NOT NULL,
 reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE fabric_cold_effect_quarantine(
 recovery_id uuid NOT NULL REFERENCES fabric_cold_recoveries(recovery_id),
 effect_id uuid PRIMARY KEY REFERENCES fabric_effect_outbox(id),
 original_status text NOT NULL,
 reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE fabric_cold_alarm_quarantine(
 recovery_id uuid NOT NULL REFERENCES fabric_cold_recoveries(recovery_id),
 alarm_id uuid PRIMARY KEY REFERENCES fabric_alarm_outbox(id),
 original_status text NOT NULL,
 reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE fabric_cold_artifact_quarantine(
 recovery_id uuid NOT NULL REFERENCES fabric_cold_recoveries(recovery_id),
 artifact_id uuid PRIMARY KEY REFERENCES fabric_artifacts(id),
 original_status text NOT NULL,
 reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
