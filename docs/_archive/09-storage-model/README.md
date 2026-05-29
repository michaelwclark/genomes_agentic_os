# Storage Model

The OS should not force every installation into the same storage backend. Use the simplest durable layer that fits the state.

![Agentic OS Storage Boundaries](../diagrams/storage-boundaries.svg)

Storage should follow authority. The question is not "where is this convenient to put?" The question is "which layer should be trusted for this kind of truth?"

## Storage Boundaries

| Storage | Use For | Do Not Use For |
| --- | --- | --- |
| Git/filesystem | Specs, templates, context packs, run logs, artifacts, config, decision records. | Concurrent queues, high-volume mutable state, locking. |
| Notion | Dashboards, approvals, work item cockpit, human-readable summaries. | Secrets, heavy event streams, rapid state mutation. |
| Database | Active state, dedupe, queue state, event history, matching, replay, high-volume lookup. | Narrative documentation, hand-authored specs. |
| Vector/memory | Retrieval, similarity, prior context hints. | Authoritative status, approvals, source of truth. |

## Data Ownership

| Data Type | Owner |
| --- | --- |
| Product docs, schemas, templates, examples | This repository. |
| Live domain context and workflow overlays | Installed OS root. |
| Code and product artifacts | Work repositories. |
| Human-facing queues and approvals | Control plane. |
| High-volume event and queue state | Database or queue. |
| Durable retrieval hints | Memory or vector store. |
| Secrets | Secret manager or environment, never docs or run logs. |

## When Filesystem Is Enough

Filesystem plus Notion is enough when:

- Work volume is low to moderate.
- Only one agent or human is mutating a work item at a time.
- Runs are mostly manual or scheduled.
- State can be recovered from files and Notion.
- Search needs are simple.

## When To Add A Database

Add a database when:

- Multiple automations can touch the same object.
- Work changes state repeatedly over time.
- You need idempotency keys and locks.
- You need to join across messages, runs, PRs, incidents, and approvals.
- You need replayable event history.
- You need reliable dedupe.
- You need matching, embeddings, or ranking.

Your PR, production issue, and daily development volumes can start with files and Notion, but the long-term OS should have a database-backed active state plane for anything automated at scale.

## Migration Path

Start with files and run logs. Add Notion when humans need cockpit visibility. Add a database when automation volume makes concurrency and dedupe real problems.

| Stage | Storage Shape | Trigger To Move Forward |
| --- | --- | --- |
| Local scaffold | Filesystem only. | Humans need dashboard visibility or approval queues. |
| Operating cockpit | Filesystem plus Notion. | Multiple automated actors touch the same objects. |
| Active state plane | Filesystem plus Notion plus database/queue. | Need locking, dedupe, replay, or event history. |
| Retrieval layer | Add memory/vector indexes over durable sources. | Agents need fast similarity or prior-learning lookup. |

## Evidence Rule

Any state transition should leave evidence in the layer that owns the truth:

- Files changed in Git should have commit or diff evidence.
- Human approval should have a control-plane approval record.
- Automation execution should have a run log.
- Database mutation should have an event or audit row.
- Durable operating changes should update the relevant context pack, workflow, automation, or decision record.
