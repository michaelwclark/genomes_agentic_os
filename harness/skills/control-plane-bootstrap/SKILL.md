# Control Plane Bootstrap

Use this skill to plan a Notion or file-backed operating control plane without making Notion the execution source of truth.

## Workflow

1. Verify the target workspace before any external write.
2. Load `templates/notion/control-plane-database-spec.md`.
3. Define Work Items, Runs, Approvals, Activity Log, Sources, and Artifacts.
4. Map filesystem objects to control-plane records.
5. Dry-run `agentic-os notion sync` before applying writes.

## Done

- Workspace verification is recorded.
- Database purposes and key properties are clear.
- Filesystem remains the source of truth.
