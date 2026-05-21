# Runtime Tracking Database Spec

Use this spec to create or verify the Notion runtime tracking layer in Genome's Notion. Do not create these databases in another workspace.

## Workspace Guard

| Check | Required Value |
| --- | --- |
| Workspace | `Genome's Notion` |
| Blocked workspace markers | `Michael Clark`, `michaelwclark`, `personal notion` |
| Apply command | `agentic-os notion track-runtime --root ~/agentic_os --apply --verified-workspace "Genome's Notion"` |

## Databases

| Database | Purpose | Key Fields |
| --- | --- | --- |
| Integrations | Track connected systems and setup readiness. | Name, Provider, Status, Credential State, Approval Gate, Last Health Check |
| Heartbeats | Track repeating runtime checks. | Name, Cadence, Enabled, Integration, Execution Target, Last Status, Last Run |
| Schedules | Track scheduled runtime commands. | Name, Cadence, Timezone, Command, Enabled, Last Queued |
| Runs | Track heartbeat, schedule, and setup run records. | Name, Kind, Status, Started At, Dry Run, Log Path, Linked Runtime Object |

## Apply Rules

- Dry-run first and review the generated record plan.
- Apply only after the workspace is verified as Genome's Notion.
- Keep credentials out of Notion. Store only the credential state and required environment variable names.
- If workspace verification fails, write a blocked local run record instead of attempting a Notion write.
