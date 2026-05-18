# Data Model Spec

The database is optional in early pilots, but the OS should be designed so active state can move into a database cleanly.

## When This Model Is Needed

Use the database-backed model when:

- Inbound messages are frequent and messy.
- Multiple automations can update the same work item.
- State changes over time and needs replay.
- Dedupe and idempotency matter.
- Search requires joins across messages, PRs, incidents, runs, and approvals.
- Matching or embeddings are part of the product.

## Core Tables

### `domains`

| Field | Purpose |
| --- | --- |
| `id` | Stable domain ID. |
| `name` | Human-readable domain name. |
| `status` | `active`, `paused`, or `archived`. |
| `config_path` | Filesystem source config. |

### `inbound_items`

| Field | Purpose |
| --- | --- |
| `id` | Stable inbound ID. |
| `domain_id` | Owning domain. |
| `source_system` | Slack, GitHub, Jira, email, Notion, meeting notes, manual. |
| `source_id` | External source identifier. |
| `source_url` | Link to original source. |
| `raw_payload_ref` | Pointer to stored raw payload. |
| `status` | Intake status. |
| `received_at` | Capture time. |

### `work_items`

| Field | Purpose |
| --- | --- |
| `id` | Stable work item ID. |
| `domain_id` | Owning domain. |
| `lane` | Engineering, support, sales, operations, etc. |
| `workflow_id` | Selected workflow. |
| `status` | OS state. |
| `priority` | Routing priority. |
| `title` | Human-readable title. |
| `next_action` | Current handoff. |

### `runs`

| Field | Purpose |
| --- | --- |
| `id` | Stable run ID. |
| `work_item_id` | Related work item. |
| `run_type` | Workflow, automation, or skill. |
| `agent` | Claude, Codex, worker, or integration. |
| `status` | Run status. |
| `started_at` | Start time. |
| `completed_at` | End time. |
| `run_log_path` | Filesystem run log. |

### `state_transitions`

| Field | Purpose |
| --- | --- |
| `id` | Stable transition ID. |
| `work_item_id` | Related work item. |
| `from_state` | Previous state. |
| `to_state` | New state. |
| `reason` | Why it changed. |
| `actor` | Human, agent, or automation. |
| `created_at` | Transition time. |

### `approvals`

| Field | Purpose |
| --- | --- |
| `id` | Stable approval ID. |
| `work_item_id` | Related work item. |
| `run_id` | Related run. |
| `requested_action` | Action needing approval. |
| `risk_level` | Low, medium, high. |
| `status` | Pending, approved, rejected, expired. |
| `decision_notes` | Human decision rationale. |

### `artifacts`

| Field | Purpose |
| --- | --- |
| `id` | Stable artifact ID. |
| `work_item_id` | Related work item. |
| `run_id` | Related run. |
| `kind` | PR, file, doc, image, report, export, etc. |
| `uri` | Location. |
| `summary` | Short explanation. |

### `external_refs`

| Field | Purpose |
| --- | --- |
| `id` | Stable ref ID. |
| `object_type` | Work item, run, approval, artifact. |
| `object_id` | Internal object ID. |
| `system` | GitHub, Jira, Slack, Notion, Sentry, etc. |
| `external_id` | External object identifier. |
| `url` | External URL. |

## Database Rule

The database owns active mutable state. It should link back to filesystem specs and Notion pages instead of duplicating long-form documents.
