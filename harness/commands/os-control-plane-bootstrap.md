# OS Control Plane Bootstrap

Use when an operator needs a Notion or file-backed control plane for work items, runs, approvals, activity, sources, and outputs.

## Procedure

1. Verify the workspace before any Notion write.
2. Start from `templates/notion/control-plane-database-spec.md`.
3. Define Work Items, Runs, Approvals, Activity Log, Sources, and Artifacts.
4. Keep routers, workflow specs, automation specs, templates, and run logs in the filesystem as source of truth.
5. Add engine-control decisions for status, retry count, approval state, and failure recovery.
6. Dry-run sync before applying any control-plane write.

## Output

Return the bootstrap target, databases, required properties, workspace verification evidence, dry-run sync status, and next action.
