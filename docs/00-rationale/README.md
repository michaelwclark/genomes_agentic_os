# Rationale

Genome's Agentic OS exists to make repeated agentic work cheaper, more reliable, and easier to resume.

The problem is not lack of agents. The problem is that every chat starts by rebuilding context: what project this is, where state lives, what process should run, what has already happened, what artifacts matter, and where the output should go.

The OS fixes that by making the operating structure explicit.

![Agentic OS Value Flow](../diagrams/value-flow.svg)

## The Value Proposition

The OS turns agent work from isolated conversations into repeatable operations.

| Without An OS | With An OS |
| --- | --- |
| Each chat starts with broad context reconstruction. | Agents load domain, workflow, and task context from known locations. |
| Decisions disappear into transcripts. | Decisions are stored in run logs, decision records, and the control plane. |
| Approval boundaries are implicit. | Workflows and automations declare approval gates before execution. |
| Automations grow as one-off scripts. | Automations share the same object model, states, and audit requirements. |
| Human dashboards drift from execution records. | Notion shows cockpit state while run logs preserve execution evidence. |

## Expected Improvements

- Fewer tokens spent on rediscovery.
- Better continuity across Claude, Codex, automations, and manual work.
- More predictable handoffs between human decisions and agent execution.
- Reusable client setups instead of bespoke one-off automation piles.
- Cleaner distinction between source code repos, operating state, and human dashboards.

## What This Is Not

- Not a replacement for project repos.
- Not a generic task manager.
- Not a single giant prompt.
- Not a web app by default.
- Not a place to hide business logic in chat history.

## Operating Principle

Every durable workflow should answer these questions without asking the human again:

1. What kind of work is this?
2. What domain owns it?
3. What context is needed?
4. What workflow or automation should run?
5. What state transition happened?
6. What evidence was produced?
7. What needs approval or follow-up?

If those answers are stored in predictable places, agents can operate with less prompt mass and less guessing.

## When The OS Is Worth It

Use this structure when work repeats, crosses tools, requires approvals, or needs to be resumed by another agent later.

Good fits:

- Pull request review and follow-up.
- Feature work from a ticket or spec.
- Meeting notes to decisions and action items.
- Production issue intake and status tracking.
- Client-facing automation delivery.
- Daily operations and recurring reports.

Poor fits:

- One-off questions with no durable output.
- Work that does not need shared context or handoff.
- Experiments where the process is not stable enough to name yet.

## Design Bias

The OS is intentionally boring infrastructure:

- Files first for specs, context, templates, and run logs.
- Notion for human visibility and approvals.
- Database only when active state needs concurrency, dedupe, locking, or replay.
- Agent memory as retrieval assistance, not as the authoritative source of status.
- Templates and schemas over prose-only operating instructions.
