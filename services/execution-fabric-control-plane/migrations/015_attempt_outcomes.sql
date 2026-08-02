-- The task result is mutable truth; preserve the result produced by the
-- specific leased worker attempt that completed it as immutable history.
ALTER TABLE fabric_attempts
  ADD COLUMN IF NOT EXISTS result jsonb;
