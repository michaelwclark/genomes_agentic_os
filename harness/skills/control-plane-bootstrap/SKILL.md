# Control Plane Bootstrap

Use this skill to plan and set up a Notion-backed (or file-backed) operating control plane for a customer OS. The filesystem is always the source of truth. Notion is a projection — a human cockpit for intake, approvals, and status. Do not make Notion the execution engine.

## When To Use

- A customer OS is installed and the operator wants a Notion dashboard for managing work items, runs, and approvals.
- You need to define the database shape before writing anything to Notion.
- You are setting up engine-control decisions (what runs automatically vs. what requires a human trigger).

## Prerequisites

- Customer OS root exists and `customer validate` passes.
- At least one domain is set up.
- The operator has identified the target Notion workspace.

---

## Procedure

### Step 1 — Workspace Verification Guard

**Never write to a Notion workspace without explicit verification.** This is a hard gate — do not skip it.

1. Ask the operator: "What is the exact name and URL of the target Notion workspace?"
2. Confirm the workspace is the customer's workspace, not Genome's personal Notion or another operator's workspace.
3. Record the workspace name and confirmation in the bootstrap plan before any write.

If the workspace cannot be confirmed, stop and report the blocker. Do not proceed.

---

### Step 2 — Load the Control Plane Spec Template

Load:

```
shared_factory/05-knowledge/templates/notion/control-plane-database-spec.md
```

This template defines the five-database shape. Review it with the operator before creating databases.

---

### Step 3 — Define the Five Databases

Every customer OS control plane requires these five databases at minimum:

| Database | Purpose |
| --- | --- |
| **Work Items** | Cross-room queue: all pending, active, and blocked work across domains. Current state, priority, owner, and agent assignment. |
| **Runs** | Execution history: one row per completed or failed run. Validation evidence, output URLs, errors, and retry count. |
| **Approvals** | Human review queue: any action requiring an explicit approval gate before execution. Customer-visible output, production changes, billing, legal, destructive actions. |
| **Activity Log** | Event stream readable by both agents and operators. Append-only. Records what ran, when, what changed, and who approved. |
| **Sources** | Registry of all connected systems: repositories, Notion pages, Slack channels, dashboards, tools, and external APIs. Maps to source map files on disk. |

**Queue database row fields (Work Items and Runs):**

```
Name, Status, Ready, Priority, Owner, Agent, Source, Output URL, Notes, Last Run, Retry Count
```

**Do not add** customer-specific IDs, private credential fields, or business-logic columns to the database spec template. Those belong in the customer profile (`customer.yml`).

---

### Step 4 — Engine Control Decisions

Before bootstrapping, record the engine control decisions in the plan file:

| Decision | Options | Default |
| --- | --- | --- |
| Run trigger | Operator-triggered / schedule / event | Operator-triggered for first pilot |
| Approval policy | Auto-approve / human-approve / approve-by-tier | Human-approve for customer-visible and production actions |
| Retry on failure | Yes / No / N times | No automatic retry without operator review |
| Notification channel | Notion comment / Slack / email | Notion comment only |
| Rollback mechanism | Manual / file revert / snapshot | Manual for first pilot |

Write these decisions to the bootstrap plan before creating any database.

---

### Step 5 — Map Filesystem to Control Plane

For each database, map the corresponding filesystem objects:

| Control Plane Database | Filesystem Source of Truth |
| --- | --- |
| Work Items | Date-prefixed packets under `<domain>/02-projects/<project>/work-items/`, plus `99-archived/` history |
| Runs | `<domain>/03-workflows/<lane>/<name>/runs/` and run-log files |
| Approvals | `<domain>/03-workflows/<lane>/<name>/runs/` approval records |
| Activity Log | `<domain>/run-log.md` entries |
| Sources | `source-map.md` and `watch-sources.yml` registry files |

**Rule:** if the filesystem and Notion disagree, the filesystem wins. Notion is updated to match the filesystem, never the reverse.

---

### Step 6 — Dry-Run Before Any Write

Before applying any Notion write:

1. Run `agentic-os notion sync --dry-run --root <customer-root>` to see what would be created or updated.
2. Review the plan output with the operator.
3. Confirm the workspace verification from Step 1 is still current.

Only after operator confirmation: apply writes.

---

### Step 7 — Record the Bootstrap

After bootstrapping:

1. Write the workspace name, database IDs, and engine control decisions to `<customer-root>/customer/control-plane-bootstrap.md`.
2. Update `<customer-root>/customer.yml` with the `notion_workspace` field if not already set.
3. Run `agentic-os customer validate --root <customer-root>` — must exit 0.

---

## Anti-Patterns (Do Not Do These)

- **Do not make Notion the execution source of truth.** Run logs and work items live on the filesystem; Notion is a read/write dashboard.
- **Do not write database IDs or workspace credentials** into reusable templates, shared configs, or source code.
- **Do not skip workspace verification.** Accidentally writing to the wrong Notion workspace is irreversible.
- **Do not create the control plane before the customer OS is validated.** The filesystem structure must exist before the projection does.
- **Do not use the Activity Log as a task queue.** It is append-only event stream, not an execution queue.

---

## Done

- Workspace is verified and recorded.
- All five databases are defined with the standard row fields.
- Engine control decisions are written to the bootstrap plan.
- Filesystem-to-control-plane mapping is documented.
- Dry-run was reviewed before any write was applied.
- Filesystem remains the source of truth.
- `customer validate` exits 0 after bootstrap.
