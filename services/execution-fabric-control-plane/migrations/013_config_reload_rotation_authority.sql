ALTER TABLE fabric_config_reload_receipts
  ADD COLUMN IF NOT EXISTS rotation_id uuid,
  ADD COLUMN IF NOT EXISTS preparation_token_hash text;

ALTER TABLE fabric_config_reload_receipts
  DROP CONSTRAINT IF EXISTS fabric_config_reload_receipts_preparation_hash_check;

ALTER TABLE fabric_config_reload_receipts
  ADD CONSTRAINT fabric_config_reload_receipts_preparation_hash_check
  CHECK (
    preparation_token_hash IS NULL OR
    preparation_token_hash ~ '^[a-f0-9]{64}$'
  );

CREATE UNIQUE INDEX IF NOT EXISTS fabric_config_reload_receipts_rotation_idx
  ON fabric_config_reload_receipts(rotation_id)
  WHERE rotation_id IS NOT NULL;
