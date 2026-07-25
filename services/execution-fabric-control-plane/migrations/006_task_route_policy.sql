ALTER TABLE fabric_tasks
  ADD COLUMN IF NOT EXISTS scheduling_class text NOT NULL DEFAULT 'background'
  CHECK (scheduling_class IN ('interactive','background'));

CREATE INDEX IF NOT EXISTS idx_fabric_tasks_running_scheduling_class
  ON fabric_tasks(scheduling_class)
  WHERE status = 'running';
