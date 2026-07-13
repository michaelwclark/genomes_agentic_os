# Runtime Tracking Database Spec

Use this spec to create or verify the Notion runtime tracking layer in Genome's Notion. Do not create these databases in another workspace.

## Workspace Guard

| Check | Required Value |
| --- | --- |
| Workspace | `Genome's Notion` |
| Blocked workspace markers | `personal notion` (extend via `NOTION_BLOCKED_WORKSPACE_MARKERS`) |
| Apply command | `agentic-os notion track-runtime --root ~/agentic_os --apply --verified-workspace "Genome's Notion"` |

## Databases

| Database | Purpose | Key Fields |
| --- | --- | --- |
| Integrations | Track connected systems and setup readiness. | Name, Provider, Status, Credential State, Approval Gate, Last Health Check |
| Execution Targets | Track workers and runtime providers. | Name, Type, Status, Owner, Health Check, Approval Required For |
| Heartbeats | Track repeating runtime checks. | Name, Cadence, Enabled, Integration, Execution Target, Last Status, Last Run, Next Due |
| Schedules | Track scheduled runtime commands. | Name, Cadence, Timezone, Command, Enabled, Last Queued, Next Due |
| Run Queue | Track dispatchable work before and during execution. | Name, Kind, Status, Approval State, Due At, Idempotency Key, Log Path |
| Approvals | Track human gates for risky runtime actions. | Name, Queue Item, Approval State, Required Gate, Owner, Decision At |
| Runs | Track heartbeat, schedule, setup, and dispatch records. | Name, Kind, Status, Started At, Finished At, Dry Run, Log Path, Linked Runtime Object |

## Apply Rules

- Dry-run first and review the generated record plan.
- Apply only after the workspace is verified as Genome's Notion.
- Keep credentials out of Notion. Store only the credential state and required environment variable names.
- If workspace verification fails, write a blocked local run record instead of attempting a Notion write.
- Record verified database IDs in `.notion-runtime-tracking/manifest.yml` after apply.
