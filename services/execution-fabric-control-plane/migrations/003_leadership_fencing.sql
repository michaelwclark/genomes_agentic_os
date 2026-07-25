ALTER TABLE fabric_state
  ADD COLUMN IF NOT EXISTS leadership_cluster_id text,
  ADD COLUMN IF NOT EXISTS leadership_receipt_id text,
  ADD COLUMN IF NOT EXISTS leadership_fence_digest text,
  ADD COLUMN IF NOT EXISTS leader_recovery_hold_until timestamptz;

ALTER TABLE fabric_state
  DROP CONSTRAINT IF EXISTS fabric_state_leadership_fence_digest_check,
  ADD CONSTRAINT fabric_state_leadership_fence_digest_check CHECK (
    leadership_fence_digest IS NULL OR
    leadership_fence_digest ~ '^[0-9a-f]{64}$'
  );
