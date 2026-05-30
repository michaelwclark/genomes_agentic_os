# 22 - Project Work Lifecycle And Conversation Auto Logging

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-30
- Target OS layer: source package, installed runtime, Codex, Claude, and customer OS installs

## Problem

Agentic OS has domain inboxes, project folders, run logs, and source-package
feature folders, but it does not yet make the work lifecycle obvious to every
agent. A user can say "I have an idea for LOS Django" or "implement
60-memory-driven-toolsmith-loop", and the agent still has to infer where to put
the idea, which files to read, which status should change, and where the
conversation record belongs.

The missing operating contract is:

```text
idea -> triage -> spec -> ready -> building -> validation -> finished -> documented
```

The OS also lacks a default conversation logging hook that writes transcripts
and tool-use summaries into the routed domain/project/work item. Without that,
the durable evidence needed by run logs, memory promotion, metrics, and the
memory-driven toolsmith loop remains scattered across harness-specific session
stores.

## Outcome

Every project gets a configurable work-item lifecycle with feature-60-style
tracking files. Agents can route a request, inspect the current lifecycle state,
read the right context for that state, update the appropriate markdowns, and
close the run with validation evidence.

The default installed OS should support these prompts without chat archaeology:

- "I have an idea for los django."
- "I have a new feature I want to build for genomes_os."
- "Let's implement 60-memory-driven-toolsmith-loop."
- "Where is this feature in the lifecycle?"
- "What did the last agent do, and what should happen next?"

Conversation auto logging should write redacted transcript artifacts to the
active work item or routed project run folder using sortable date-and-slug names.

## Canonical Lifecycle

| State | Meaning | Primary Files |
| --- | --- | --- |
| `captured` | Raw idea exists, no scope decision yet. | `IDEA.md`, project `status.md`, inbox `triage.md` |
| `triaged` | Domain/project and destination are chosen. | `JUDGMENT.md`, `work.yml` |
| `specified` | Problem, outcome, scope, and acceptance are written. | `SPEC.md` |
| `ready` | Plan and context are complete enough to build. | `PLAN.md`, `NEXT.md` |
| `building` | Implementation is underway. | `WORKLOG.md`, `INVESTIGATION.md` |
| `validating` | Implementation exists and proof is being gathered. | `HOLDOUT_QA.md`, `HOLDOUT_QA_RESULTS.md` |
| `finished` | Work is complete with validation evidence. | `SUMMARY.md`, `WORKLOG.md` |
| `documented` | Docs, memories, indexes, and downstream trackers are updated. | `MEMORY.md`, project `status.md`, docs/index files |
| `blocked` | Work cannot move without a decision, access, or external change. | `NEXT.md`, `JUDGMENT.md` |
| `archived` | Work is closed and no longer active. | archive index and final `SUMMARY.md` |

Existing source-package feature folders may keep `feature.yml`. Installed
runtime work items should use `work.yml`; `feature.yml` is accepted as an alias
for source-package compatibility.

## Runtime Shape

Project work items should live under the project that owns the work:

```text
<domain>/02-projects/<project>/work-items/<work_id_slug>/
  work.yml
  IDEA.md
  SPEC.md
  PLAN.md
  INVESTIGATION.md
  JUDGMENT.md
  HOLDOUT_QA.md
  HOLDOUT_QA_RESULTS.md
  WORKLOG.md
  SUMMARY.md
  NEXT.md
  MEMORY.md
  artifacts/
  logs/
    conversations/
      YYYY_MM_DD_<slug>.jsonl
      YYYY_MM_DD_<slug>_tool_calls.jsonl
      YYYY_MM_DD_<slug>_tool_calls.md
```

Domain-level ideas that are not tied to a known project still start in:

```text
<domain>/01-inbox/raw-ideas.md
<domain>/01-inbox/triage.md
```

Reusable OS product ideas live in the source-package `PLANS/` backlog and are
installed into:

```text
harness/shared_factory/05-knowledge/plans/
harness/shared_factory/05-knowledge/plans/future-ideas/
```

Older installs may still have a top-level `shared_factory/`. Migration must
preserve that state and either mirror or move it into `harness/shared_factory/`
behind an explicit migration plan. New docs and templates should describe
`harness/shared_factory/` as the canonical shared OS product layer, not as a
normal user-facing domain.

## Project Configuration

Each project should be able to override where lifecycle artifacts go and what
"promotion" means:

```yaml
work_lifecycle:
  enabled: true
  work_items_root: work-items
  default_state: captured
  transcript_logging:
    enabled: true
    include_raw_transcript: true
    include_tool_call_jsonl: true
    include_tool_call_markdown: true
    redaction_policy: strict
  spec_destination:
    type: local
    path: work-items
  external_tracker:
    type: none
```

For `genomes_agentic_os`, source-package work should map to numbered folders
under `features/` plus source backlog entries under `PLANS/`.

For `los_app_los_django`, project config can route after `specified` into Jira:

```yaml
work_lifecycle:
  enabled: true
  work_items_root: work-items
  spec_destination:
    type: jira
    project_key: DLOS
    local_mirror: true
  external_tracker:
    type: jira
    key_field: jira_key
```

The local OS work item remains the evidence mirror even when Jira becomes the
engineering source of truth after specification.

## Agent State Contract

Agents should use the lifecycle state to decide what to read and write.

| User Intent | Agent Action |
| --- | --- |
| New rough idea | Route to domain/project, append to inbox or create `IDEA.md`, set `captured`. |
| Promote idea to spec | Read `IDEA.md`, project `status.md`, `source-map.md`, then write `SPEC.md` and `JUDGMENT.md`. |
| Start implementation | Read `SPEC.md`, `PLAN.md`, `NEXT.md`, `JUDGMENT.md`, project `source-map.md`, then set `building` and append `WORKLOG.md`. |
| Resume numbered feature | Open the matching work item or source `features/<nn>-.../`, read `work.yml` or `feature.yml`, `SPEC.md`, `PLAN.md`, `WORKLOG.md`, `NEXT.md`, and current validation files. |
| Validate | Read `HOLDOUT_QA.md`, execute the validation plan, write `HOLDOUT_QA_RESULTS.md`, update `SUMMARY.md`. |
| Finish/document | Update `SUMMARY.md`, `MEMORY.md`, project `status.md`, indexes, and any configured external tracker. |

Harness startup context should tell agents to route first, then read the
state-specific files before editing. Closeout context should require an updated
`WORKLOG.md`, `NEXT.md`, and validation evidence for substantive work.

## Conversation Auto Logging

Add a default non-blocking hook that reads harness stop/session payloads,
discovers the transcript path and current working directory, routes to the
nearest OS domain/project/work item, redacts sensitive values, and writes:

- `YYYY_MM_DD_<slug>.jsonl`: the original conversation transcript when available
  and allowed by project policy.
- `YYYY_MM_DD_<slug>_tool_calls.jsonl`: structured tool calls, MCP calls, shell
  commands, skills, agents, and validation commands extracted from the
  transcript.
- `YYYY_MM_DD_<slug>_tool_calls.md`: human-readable summary with source paths,
  commands, outcomes, and redaction notices.

Use `YYYY_MM_DD` rather than `MM_DD_YYYY` so filesystem ordering is stable.
Slug source should prefer active work item slug, then project slug, then a
sanitized first user-intent summary.

The hook must be best-effort and must never block the agent from finishing. It
may emit a short warning into hook logs, but it should not print transcript
contents to chat.

## Hook Gap Analysis

| Current Hook Or Surface | Covers | Missing For OS Value Proof | Proposed Idea |
| --- | --- | --- | --- |
| `memory-session-start.sh` | Reminds agents that losmon-memory exists. | Does not route to domain/project or tell agents which lifecycle files to read. | Add lifecycle-aware startup context injection. |
| `memory-stop.sh` | Reminds agents to capture durable learnings. | Reminder only; no proof that work logs, next steps, or validation were updated. | Add closeout checklist hook or command. |
| `harness-emit-trace.sh` | Writes a summary `AGENT_TRACE` memory record. | Does not copy transcript, extract tool calls, or attach evidence to a project work item. | Add conversation auto logger. |
| `context-mode-cache-heal.mjs` | Repairs stale Claude context-mode plugin symlinks. | Claude-specific maintenance; not an OS lifecycle hook. | Keep as maintenance hook, but track it separately from operating-value hooks. |
| `run-logger` skill and `os-run-log.md` | Manual run-log procedure. | Agents can skip it, and project feature folders have no guaranteed sidecar logs. | Add run-log discoverability plus auto-created conversation sidecars. |
| `plan capture` | Routes OS/domain/project ideas. | Project ideas currently append to `status.md` instead of creating a full work packet. | Promote project idea capture into lifecycle work-item creation. |
| `route/context build` | Identifies target and context. | Does not yet return lifecycle state or required next files. | Add lifecycle state to route/context output. |
| `validate` and `doctor` | Structural health checks. | Do not detect missing lifecycle files, stale `building` items, or undocumented finished work. | Add lifecycle doctor/validation checks. |

## Scope

- Define the canonical project work-item file set and status vocabulary.
- Add templates for work-item tracking files.
- Add project config fields for lifecycle routing, transcript logging, and
  external tracker promotion.
- Extend idea capture so project ideas can create work-item packets, not only
  append to project status.
- Extend routing/context output with lifecycle state and state-specific files.
- Add conversation auto logging hook and redacted tool-call extraction.
- Add lifecycle-aware closeout guidance for agents.
- Add validation/doctor checks for stale, incomplete, or undocumented work
  items.
- Add docs showing how `genomes_agentic_os` local features and LOS Jira-backed
  features use the same lifecycle with different promotion policies.

## Out Of Scope

- Replacing Jira for LOS engineering execution.
- Writing to Notion without verified Genome's Notion access.
- Storing secrets, raw credentials, or unredacted token-shaped values in logs.
- Making hooks blocking by default.
- Moving existing installed `shared_factory` state without a migration plan.
- Changing feature 60 implementation itself.

## Acceptance Criteria

- A fresh install includes work-item templates and project lifecycle config
  defaults.
- A project idea can create a work item with the feature-60-style markdown stack.
- `agentic-os route` or context build can point to the active work item and list
  state-specific files to read.
- A request naming `60-memory-driven-toolsmith-loop` can be resolved to the
  existing source-package feature folder and its next required files.
- Project config can route a specified LOS Django item to Jira while retaining a
  local OS mirror.
- The conversation logging hook writes redacted transcript and tool-call sidecars
  under the routed work item or run log.
- Hook failures are non-blocking and visible in local hook logs.
- `validate` or `doctor` reports missing required lifecycle files, stale
  `building` work, finished-but-undocumented work, and logs containing
  token-shaped values.
- Docs explain `harness/shared_factory` as the canonical shared product layer and
  preserve migration safety for older top-level `shared_factory` installs.

## Validation

- Unit tests for lifecycle status transitions and required-file checks.
- CLI tests for project idea capture, work-item creation, and route/context
  lifecycle output.
- Hook tests with synthetic Claude and Codex stop payloads.
- Redaction tests for token-shaped strings in transcript and tool-call sidecars.
- Temp-root smoke:
  - init root
  - create project
  - capture project idea
  - promote to spec
  - simulate conversation logging hook
  - validate lifecycle state
- LOS policy fixture that proves `specified` can promote to a Jira-targeted
  mirror without live Jira writes.
- Source-package fixture that proves feature 60 is discoverable and resumable.

## Rollout Notes

This must be additive. Existing projects that only have `status.md` keep working.
Lifecycle work-item creation should be opt-in per project at first, then become
the default for new projects after validation.

Conversation logging should default to enabled for local Genome installs and
disabled or transcript-summary-only for customer installs until the customer
profile explicitly opts in.

Do not overwrite installed work logs, run logs, or local project status files.
