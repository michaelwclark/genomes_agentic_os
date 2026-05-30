# Feature Spec: Memory Driven Toolsmith Loop

## Status

- Status: planned
- Owner: Genome operators
- Created: 2026-05-30
- Target OS layer: installed runtime, source package, shared references, harness skills

## Problem

Tools that claim to "get better over time" are usually not magic. The useful
mechanism is a scheduled reviewer that reads durable evidence, identifies
recurring friction, and proposes new rules, commands, skills, validation checks,
or workflow changes.

Agentic OS already has the pieces: durable memory, run logs, event graph,
runtime schedules, command templates, shared references, skill registries, and
feature folders. What is missing is the explicit loop that turns recurring
operator experience into reviewable toolsmith work without quietly mutating the
system.

## Outcome

Agentic OS should have a local, auditable self-improvement loop:

- It runs on a schedule or on demand.
- It reads memory, run logs, events, workflow closeouts, validation failures,
  repeated shell/tool use, and existing command/skill registries.
- It emits evidence-backed improvement proposals.
- It can promote approved proposals into feature specs, rule updates, command
  prompts, skill drafts, or validation tasks.
- It never treats "improvement" as hidden model training or uncontrolled
  auto-editing.

## Operating Principle

This feature should make the mechanism boring and inspectable:

```text
durable evidence
  -> scheduled analysis prompt/tool
  -> clustered improvement opportunities
  -> scored proposals
  -> approval gate
  -> generated feature/spec/skill/command draft
  -> tests and validation
  -> optional install/update
```

The first version should optimize for trustworthy proposals, not autonomous
mutation.

## Inputs

- Project and OS memories:
  - losmon-memory `memory_read`
  - project-level `MEMORY.md`
  - shared reference `decision-log.md`
- Run evidence:
  - `shared_factory/06-runs-and-logs/`
  - workflow closeout records
  - runtime supervisor logs
  - event graph summaries and dead letters
- Tooling evidence:
  - command registry
  - skill registry
  - host tool registry
  - validation and doctor results
  - repeated shell commands or manual sequences
- External evidence, only when configured:
  - GitHub PR check failures
  - Jira/Notion card churn
  - Slack or source watcher events

## Improvement Opportunity Types

- `memory_rule`: a durable rule or troubleshooting note should be written.
- `reference_update`: shared knowledge should change under
  `shared_factory/05-knowledge/references/`.
- `skill_update`: a new or existing skill should encode a repeated workflow.
- `command_prompt`: a harness command should be added or revised.
- `tool_wrapper`: a script or CLI command should replace repeated manual shell
  work.
- `doctor_check`: validation should catch a recurring broken state.
- `feature_spec`: the work is big enough to become a numbered feature folder.
- `backlog_item`: the idea is useful but not ready for implementation.

## Scoring

Each proposal should include a transparent score:

- Frequency: how often the pattern appeared.
- Severity: how much time, risk, or failure it caused.
- Reuse: whether it applies across projects or only one local case.
- Confidence: how directly the evidence supports the recommendation.
- Blast radius: how risky the resulting change would be.
- Staleness: whether the evidence is recent enough to act on.

Low-confidence proposals stay as notes. High-confidence, low-risk proposals can
be queued for operator approval.

## Runtime Surfaces

Source templates should install runtime files under the existing shared factory
structure:

```text
shared_factory/00-control-plane/self-improvement.yml
shared_factory/05-knowledge/templates/runtime/self-improvement-review.yml
shared_factory/05-knowledge/templates/runtime/self-improvement-proposal.yml
shared_factory/05-knowledge/commands/os-self-improvement.md
shared_factory/05-knowledge/skills/toolsmith-reviewer/SKILL.md
shared_factory/06-runs-and-logs/self-improvement/
shared_factory/06-runs-and-logs/self-improvement/proposals/
```

The control-plane file should define cadence, enabled analyzers, proposal
thresholds, allowlisted mutation targets, cooldown windows, redaction rules, and
approval requirements.

## CLI Shape

The exact flags can change during implementation, but the first usable shape
should look like this:

```bash
agentic-os self-improvement run --root ~/agentic_os --dry-run
agentic-os self-improvement run --root ~/agentic_os --apply
agentic-os self-improvement list --root ~/agentic_os
agentic-os self-improvement show <proposal_id> --root ~/agentic_os
agentic-os self-improvement promote <proposal_id> --target feature-spec --root ~/agentic_os
```

Dry-run prints the review and writes no proposals. Apply writes proposal files
only. Promote creates a draft artifact but should still avoid installing or
editing live harness surfaces without an explicit operator step.

## Scope

- Add source templates and schemas for self-improvement reviews and proposals.
- Add a dry-run-by-default CLI analyzer.
- Add apply mode that writes proposal records to the installed OS root.
- Add proposal dedupe and cooldown handling.
- Add redaction checks before proposal files are written.
- Add promotion into numbered feature draft, skill draft, command prompt draft,
  or reference-update patch plan.
- Integrate a scheduled target with the runtime supervisor/schedule layer.
- Add a `toolsmith-reviewer` skill for agents to execute the review manually.
- Add docs and validation so a fresh agent can operate the loop.

## Out Of Scope

- Training a model or claiming hidden model-level learning.
- Autonomous edits to global Codex, Claude, Cursor, Notion, or shell
  configuration.
- Unreviewed writes to Genome's Notion or any other workspace.
- Pulling private external sources unless a source watcher/integration is
  explicitly configured and authorized.
- Replacing losmon-memory, context-mode, or existing feature/spec workflows.
- Installing generated tools or skills without test evidence and approval.

## Affected Surfaces

- CLI: new `self-improvement` command group.
- Installer/update behavior: managed templates install additively through docs
  update/runtime init.
- Runtime OS files: self-improvement control plane, review logs, proposal queue.
- Harness commands or skills: `os-self-improvement.md` and
  `toolsmith-reviewer/SKILL.md`.
- Notion control plane: optional proposal tracking only after Genome's Notion
  workspace is verified.
- Tests: schema validation, dry-run/apply behavior, redaction, dedupe, promotion.

## Acceptance Criteria

- `agentic-os self-improvement run --dry-run` reads local evidence and prints a
  review without writing files.
- `agentic-os self-improvement run --apply` writes proposal files only under
  `shared_factory/06-runs-and-logs/self-improvement/proposals/`.
- Every proposal includes evidence references, opportunity type, score,
  recommended artifact, approval requirement, and validation plan.
- The analyzer redacts secrets and refuses to write proposals containing token-
  shaped values.
- Duplicate proposals are merged or suppressed within a configurable cooldown.
- Scheduled execution can be wired through the existing runtime supervisor
  without one failed analyzer aborting the full supervisor tick.
- Promotion can create a draft feature folder, skill draft, command prompt draft,
  or reference-update plan from an approved proposal.
- Validation checks fail when required templates or schemas are missing.
- Tests cover dry-run, apply, dedupe, redaction, promotion, and scheduler
  integration.

## Validation

- Unit tests for proposal scoring, redaction, dedupe, and cooldown logic.
- CLI tests for dry-run/apply/list/show/promote.
- Temp-root smoke:
  - `runtime init`
  - seed memory/run-log/evidence files
  - dry-run self-improvement review
  - apply proposal write
  - promote one approved proposal to a draft feature folder
  - `validate`
- Holdout QA with seeded noisy logs, secret-shaped values, duplicate evidence,
  stale evidence, and low-confidence recommendations.

## Rollout Notes

This must be additive. Existing installed OS roots should receive templates,
commands, skills, and schemas without overwriting local proposals or operator
configuration.

Default state should be disabled or dry-run. Operators can enable scheduled
proposal writes after inspecting the control-plane config.

For Notion, proposal tracking may only apply after the workspace is verified as
Genome's Notion.

## Risks

- Prompt injection from logs or memory could steer generated proposals.
- Secret-bearing evidence could leak into proposal files.
- Overeager proposal generation could create churn.
- Bad proposals could encode one-off mistakes as global rules.
- Autonomous mutation could damage harness trust.

## Mitigations

- Treat all evidence as untrusted input.
- Use allowlisted output types and paths.
- Keep proposals evidence-cited and reviewable.
- Require explicit approval before promotion.
- Keep live harness/global config mutation out of the first implementation.
- Run redaction before write and again before promotion.
- Prefer project-local proposals unless the evidence proves cross-project reuse.
