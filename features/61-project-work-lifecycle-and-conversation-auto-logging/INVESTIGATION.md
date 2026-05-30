# Investigation

## Existing Shape

Feature 60 has the tracking stack the OS should generalize:

- `feature.yml`
- `SPEC.md`
- `PLAN.md`
- `INVESTIGATION.md`
- `JUDGMENT.md`
- `HOLDOUT_QA.md`
- `HOLDOUT_QA_RESULTS.md`
- `WORKLOG.md`
- `SUMMARY.md`
- `NEXT.md`
- `MEMORY.md`

The installed OS already has domain inboxes, project folders, run logs, and
shared plans, but project ideas currently do not automatically become full work
packets.

## Routing Findings

- Reusable OS product ideas belong in source `PLANS/` and install to
  `harness/shared_factory/05-knowledge/plans/`.
- Domain-level rough ideas belong in `<domain>/01-inbox/raw-ideas.md`.
- Project-owned work should have a durable packet under
  `<domain>/02-projects/<project>/work-items/`.
- A project config should decide whether a specified item promotes to a local
  feature folder, Jira, Notion, or another external tracker.

## Shared Factory Finding

`shared_factory` should not behave like an ordinary work domain. It is the shared
OS product layer for templates, plans, registries, commands, skills, references,
and reusable patterns. New source docs should use `harness/shared_factory/` as
canonical. Older installs with top-level `shared_factory/` need a migration path,
not silent deletion or overwrite.

## Auto Logging Finding

The current hook set can remind agents and write a memory trace, but it does not
put the conversation transcript or tool-use evidence in the routed project work
item. That makes later review, metrics, and memory-driven toolsmith analysis
weaker than the OS model promises.

## Hook Comparison

| Surface | Current Value | Missing |
| --- | --- | --- |
| `memory-session-start.sh` | Injects memory discipline. | Lifecycle-aware route/read instructions. |
| `memory-stop.sh` | Reminds durable capture. | Proof that work item files were updated. |
| `harness-emit-trace.sh` | Emits a summary AGENT_TRACE. | Transcript copy and tool-call sidecars. |
| `context-mode-cache-heal.mjs` | Maintains Claude context-mode cache. | Not tied to project work lifecycle. |
| `os-run-log.md` | Defines manual run logging. | Auto-created project conversation artifacts. |
| `plan capture` | Durable idea routing. | Full project work packet creation. |
| `route/context` | Finds domain/project context. | Lifecycle state and required file list. |
| `validate/doctor` | Structural checks. | Lifecycle completeness and stale-state checks. |

## Follow-On Ideas

1. Project work-item lifecycle command group.
2. Conversation auto logging hook.
3. Tool-call extraction and redaction sidecars.
4. Lifecycle-aware startup context injector.
5. Closeout checklist hook or command.
6. Lifecycle state in route/context output.
7. Project policy adapters for Jira, Notion, and local source features.
8. Lifecycle doctor and validation checks.
9. Metrics refresh from lifecycle state, validation evidence, and conversation logs.
