# Plan

1. Run the full CLI scaffold test suite.
2. Create a disposable OS root.
3. Add a project, workflow, automation, and run log.
4. Run `notion plan-sync` and inspect discovered object kinds.
5. Confirm `notion sync --apply` refuses without `--verified-workspace`.
6. Apply with `--verified-workspace "Genome's Notion"`.
7. Run a dry run and confirm all actions are no-op.
