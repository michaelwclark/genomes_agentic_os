# Feature Spec: Project Work Lifecycle And Conversation Auto Logging

## Status

- Status: planned
- Owner: Genome operators
- Created: 2026-05-30
- Target OS layer: source package, installed runtime, Codex, Claude, and customer OS installs
- Source plan: `PLANS/22-project-work-lifecycle-and-conversation-auto-logging.md`

## Problem

Feature 60 shows the right source-work packet shape: spec, plan, investigation,
judgment, worklog, QA, summary, next steps, and local memory. That shape should
not be unique to the source repo. Every OS project needs the same stateful packet
so agents know where an idea lives, how it becomes a spec, what is being built,
what was validated, what is finished, and what still needs documentation.

The OS also needs default conversation logging. The point of the domain/project
filesystem is durable operational memory; conversation transcripts and tool-use
summaries should land in the domain/project/work item that owns the work.

## Outcome

The installed OS gets a configurable project lifecycle:

```text
idea -> triage -> spec -> ready -> building -> validation -> finished -> documented
```

Each project can decide whether specified work stays local, becomes a source
feature folder, becomes a Jira ticket, becomes a Notion record, or uses another
tracker. Agents use the same lifecycle contract regardless of destination.

Conversation logging becomes a default non-blocking hook that writes redacted
transcripts and tool-call sidecars into the active work item or run log.

## Operating Principle

The filesystem remains the source of truth. External systems are projections or
promotion targets:

```text
prompt
  -> route to domain/project/work item
  -> read lifecycle state and required files
  -> update markdown evidence
  -> optionally promote to Jira/Notion/source feature
  -> validate
  -> log transcript and tool calls
  -> close with summary, next step, memory, and docs
```

## Runtime File Contract

Installed project work item:

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
  logs/conversations/
```

Source-package feature folders can keep the existing `feature.yml` name. The OS
should treat `feature.yml` and `work.yml` as equivalent lifecycle metadata with
different local conventions.

## Conversation Log Naming

Use sortable date-first names:

```text
YYYY_MM_DD_<slug>.jsonl
YYYY_MM_DD_<slug>_tool_calls.jsonl
YYYY_MM_DD_<slug>_tool_calls.md
```

The slug should come from the active work item when possible. If there is no
active work item, use the project slug or a sanitized first user intent.

## Project Policy Examples

`genomes_agentic_os`:

- Captured OS product ideas go to `PLANS/` or `PLANS/future-ideas`.
- Buildable work gets a numbered `features/<nn>-<slug>/` folder.
- The feature folder owns source-package implementation state.

`los_app_los_django`:

- Captured product ideas start in the LOS project work item.
- Once specified, the configured promotion target is Jira.
- The local OS work item keeps conversation logs, source references, validation
  evidence, and the Jira key.

## Scope

- Add the source plan for this feature.
- Define the lifecycle status vocabulary.
- Define templates and required files for project work items.
- Define project config fields for lifecycle routing and transcript logging.
- Define agent read/write rules for each lifecycle state.
- Define the conversation auto logging hook and sidecar artifacts.
- Analyze existing hooks against the OS value proof.
- Create follow-on ideas for missing hook/lifecycle enforcement pieces.

## Out Of Scope

- Implementing the CLI/hook code in this planning pass.
- Writing live Jira or Notion records.
- Moving existing installed `shared_factory` data.
- Changing feature 60 itself.

## Affected Surfaces

- CLI: future `plan capture`, `project work-item`, `route`, `context`, `validate`, and `doctor` behavior.
- Installer/update behavior: new templates and hook files installed additively.
- Runtime OS files: project work item folders, lifecycle config, conversation logs.
- Harness commands or skills: startup routing, run logging, closeout, and hook docs.
- Notion control plane: optional projection only after workspace verification.
- Tests: lifecycle templates, routing, hook payloads, redaction, project policies.

## Acceptance Criteria

- The plan exists under `PLANS/` and appears in `PLANS/README.md`.
- The feature packet mirrors feature 60's tracking style.
- The spec explains where ideas, specs, build state, validation, finished work,
  and documentation live for each project.
- The spec defines how `genomes_agentic_os` local features and LOS Jira-backed
  features share the same lifecycle.
- The spec defines transcript and tool-call logging artifacts.
- Existing hooks are analyzed and missing hook ideas are recorded.

## Validation

Planning-pass validation:

- Confirm files exist and cross-references are correct.
- Confirm no live installed OS files were mutated.
- Confirm no Notion/Jira writes were attempted.

Implementation validation is defined in the source plan.

## Rollout Notes

The first implementation should be additive and dry-run friendly. For existing
projects, do not require a full work-item packet until a project config opts in
or a migration plan creates missing files.
