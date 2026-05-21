# Cliefnotes-Derived Markdown Formats

These are the working formats agents should use when reviewing or extending the scaffold. The generated templates in `templates/` are the copyable source of truth.

## Root Router

Root routers should stay short. Their job is to pick the domain.

Source file: `ROUTER.md`. `AGENTS.md`, `CLAUDE.md`, and `AGENT.md` should be pointers to it.

Required sections:

- `# Agent Router`
- `## Routing Table`
- `## Operating Rules`
- `## Standard Lanes`
- `## Approval Defaults`

Required rule: do not create active work at root. Route into a domain.

## Domain Context

Domain `CONTEXT.md` teaches the room.

Required sections:

- Purpose.
- Inputs.
- Process.
- Output folders.
- What to load.
- Tools and skills.
- Done means.
- Standing context.
- Work style.
- Common tasks.
- Update rule.

Use this for durable domain behavior, room routing, and load/skip rules, not one-off task state. If the file starts turning into an encyclopedia, move stable reference material to `REFERENCES.md` or `05-knowledge/`.

## Domain References

Domain `REFERENCES.md` is the durable source map.

Track:

- Source systems.
- Example outputs.
- Reusable prompts or briefs.
- Known gaps.

Link to sources instead of pasting full transcripts or private docs.

## Workflow Pre-Build Chain

Every build-capable workflow should move through these files in order:

| File | Job |
| --- | --- |
| `outcome-brief.md` | Define done in one sentence and name scope, constraints, acceptance evidence, and stop conditions. |
| `alignment-questions.md` | Capture operator answers before the PRD is trusted. |
| `prd.md` | Turn the outcome into requirements, source systems, safety boundaries, and validation. |
| `implementation-plan.md` | Break the work into stages, risks, file/system scope, validation, and dispatch split. |
| `dispatch-handoff.md` | Tell a fresh agent exactly what to load, own, avoid, verify, and hand back. |
| `progress.md` | Preserve current state, blockers, resume point, decisions, and next action. |
| `quick-reference.md` | Keep the run checklist and common failure responses on one page. |

## Outcome Brief

Minimum fields:

```text
# Outcome Brief: <workflow>

## Definition Of Done
One sentence: what exists, who uses it, and what proves it works.

## In Scope

## Out Of Scope

## Constraints

## Acceptance Criteria

## Stop Conditions

## Open Questions
```

## Alignment Questions

Ask these before the agent starts planning:

- What should exist when this is done?
- Who or what will use it?
- What systems may be read?
- What systems may be written?
- What must not change?
- What proof will show correctness?
- What should stop the run?

## PRD

Minimum fields:

- Problem.
- Outcome.
- Users and use cases.
- In scope and out of scope.
- Requirements with acceptance evidence.
- Data and source systems.
- Approval and safety rules.
- Validation.
- Open questions.

## Implementation Plan

Minimum fields:

- Ordered build stages.
- Files and systems in scope.
- Dependencies and assumptions.
- Risk register.
- Validation plan.
- Orchestration split.
- Dispatch plan.

Use scripts, tests, schemas, or parsers for deterministic checks. Use AI for judgment-heavy synthesis. Use humans for risky commitments and approvals.

## Dispatch Handoff

Minimum fields:

- Target agent or harness.
- Outcome.
- Required sources to load.
- Ownership.
- Instructions.
- Constraints.
- Verification.
- Stop conditions.
- Handoff back.

If multiple agents work in parallel, every handoff must name file or responsibility ownership.

## Progress

Use `progress.md` for session persistence:

```text
Status:
Last completed action:
Current blocker:
Resume from:
Next action:
```

Update it before a session ends when the workflow is not done.

## Workflow Documentation Template

Use this shape when turning a repeatable human workflow into a spec:

```text
# Workflow: <name>

## Trigger

## Starting Point

## Steps

## End State

## Variations

## Worth Automating
```

Move it into `03-workflows` first. Move it to `04-automations` only after stable runs prove it is safe.

## Automation Worthiness

An automation candidate should pass these checks:

- It happens often enough to matter.
- The steps are stable.
- The action has a clear start and end.
- The expected output can be verified.
- Login, permission, and page-layout issues are understood.
- Failure can be logged and retried or routed.
- Risky writes require approval.

## Inbox And Calendar Guardrails

Default permission posture:

- Read and summarize: allowed when source access is approved.
- Draft: allowed as `prepare`.
- Send, cancel, archive, delete, unsubscribe, merge, deploy, bill, sign, or modify legal records: ask first unless a written domain rule explicitly pre-approves the exact action.
- Money, contracts, HR, medical, legal, credentials, production data, and key client commitments: ask first.

## Run Log

Every substantive run records:

- Metadata.
- Input.
- Context loaded.
- Session continuity.
- Actions taken.
- Validation.
- Artifacts.
- State update.
- Memory writebacks.
- Handoff.

If the next agent cannot resume from the run log and `progress.md`, the run was under-recorded.
