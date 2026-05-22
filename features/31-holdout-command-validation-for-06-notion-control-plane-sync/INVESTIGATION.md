# Investigation

The Notion sync path is local and guarded. `plan-sync` and `sync --dry-run`
build action lists from runtime files. `sync --apply` verifies the expected
workspace and writes `.notion-sync/mapping.yml`.

The holdout creates a runtime root with a project, workflow, automation, and run
log so the planner sees all expected object families.
