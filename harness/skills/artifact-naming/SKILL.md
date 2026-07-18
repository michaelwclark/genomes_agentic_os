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
3. Run `agentic-os naming migrate --root <root>` before changing existing names.
4. Review collisions and the proposed creation dates.
5. Use `--apply` only after a backup destination is writable.
6. Verify `agentic-os naming migrate` returns zero moves afterward, refresh
   `agentic-os work active-now`, and run strict validation.
7. Keep the migration receipt and backup path in the owning work item.

The default enabled format is `MMDDYY-` (`%m%d%y` and `-`). Stable internal
filenames such as `work.yml`, `run-log.md`, and `artifact.json` are not renamed.
