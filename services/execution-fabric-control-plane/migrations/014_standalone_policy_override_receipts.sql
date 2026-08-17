ALTER TABLE fabric_config_reload_receipts
  ADD COLUMN IF NOT EXISTS decision text,
  ADD COLUMN IF NOT EXISTS recovery_action text,
  ADD COLUMN IF NOT EXISTS operator_id text,
  ADD COLUMN IF NOT EXISTS override_reason text,
  ADD COLUMN IF NOT EXISTS approval_reference text,
  ADD COLUMN IF NOT EXISTS maintenance_window_start timestamptz,
  ADD COLUMN IF NOT EXISTS maintenance_window_end timestamptz,
  ADD COLUMN IF NOT EXISTS authorization_issued_at timestamptz;

ALTER TABLE fabric_config_reload_receipts
  ADD CONSTRAINT fabric_config_reload_receipts_override_fields_check
  CHECK (
    (operator_id IS NULL AND override_reason IS NULL AND approval_reference IS NULL AND
     maintenance_window_start IS NULL AND maintenance_window_end IS NULL)
    OR
    (operator_id IS NOT NULL AND override_reason IS NOT NULL AND approval_reference IS NOT NULL AND
     maintenance_window_start IS NOT NULL AND maintenance_window_end IS NOT NULL AND
     maintenance_window_end > maintenance_window_start)
  );

ALTER TABLE fabric_config_reload_receipts
  ADD CONSTRAINT fabric_config_reload_receipts_decision_check
  CHECK (
    decision IS NULL OR
    decision IN ('policy_reload_applied','standalone_policy_override_applied')
  );
