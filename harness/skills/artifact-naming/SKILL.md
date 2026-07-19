---
name: artifact-naming
description: Inspect, apply, or restore the configurable date-prefix convention for durable Agentic OS artifacts.
---

# Artifact Naming

Use this skill when creating, inspecting, migrating, or repairing work-item,
worktree, conversation-log, async-run, run-log, report-run, development-run, or thread
closeout names.

1. Read `harness/config/artifact-naming.yml` before choosing a durable entity name.
2. Use the owning CLI or API; do not hand-prefix names when the generator is available.
3. Run `agentic-os naming migrate --root <root> --preflight` before changing existing names.
4. Review collisions, creation dates, rewrite size, backup size, and every preflight risk.
5. Use `--apply` only through `agentic-os-quiet-run`, with a wall-clock timeout
   and a writable backup destination. Supply a verified prior full backup with
   `--recovery-backup-archive` when continuing an interrupted migration.
6. Do not rewrite historical log, run, evidence, snapshot, completed-work, or
   generated-artifact contents. Keep the move journal, progress snapshot, and
   terminal receipt even when an apply is interrupted or rolled back.
7. Verify `agentic-os naming migrate` returns zero moves afterward, refresh
   `agentic-os work active-now`, and run strict validation.
8. Keep the migration receipt and both backup paths in the owning work item.

The default enabled format is `MMDDYY-` (`%m%d%y` and `-`). Stable internal
filenames such as `work.yml`, `run-log.md`, and `artifact.json` are not renamed.
