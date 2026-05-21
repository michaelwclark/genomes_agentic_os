# Feature Spec: Client Automation And Control Plane Playbooks

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, customer OS installs, and Notion control plane

## Problem

The factory exports include strong customer automation discovery, automation-fit, Notion control-plane, and handoff patterns. Those patterns are currently scattered across factory docs and are not first-class in `genomes_agentic_os`.

Customer OSes need more than folders. They need a repeatable way to:

- discover valuable repeated work,
- decide whether the work should be a workflow, automation, or manual runbook,
- define the control-plane database shape,
- preserve human approval gates,
- leave the customer with a runbook and measurable success criteria.

## Factory Sources To Adapt

| Source | Pattern To Preserve |
| --- | --- |
| `factory/_notion_school/07-client-factory-playbook.md` | Discovery questions, good/bad first automation filters, client brief shape, value-pricing inputs, data boundaries, handoff deliverables. |
| `factory/_notion_school/08-skill-roadmap.md` | `factory-intake`, `factory-plan`, `factory-session`, `context-audit`, and `client-automation-brief` skill shapes. |
| `factory/_notion_clarks_consulting_school/04-notion-control-plane.md` | Notion as operator cockpit, queue database shape, activity log fields, state machine, engine control, stable weekly plan page. |
| `factory/_notion_clarks_consulting_school/06-client-automation-playbook.md` | Automation fit matrix, two-week pilot shape, customer deliverables, security/credential notes, teaching/training path. |
| `factory/_notion_agentic_operating_system_manual/*` | Domain/lane source-of-truth model, workflow and automation layouts, practical walkthrough candidates. |

## Templates To Add

```text
templates/customer/client-automation-brief.md
templates/customer/automation-fit-matrix.md
templates/customer/customer-handoff-checklist.md
templates/notion/control-plane-database-spec.md
```

## Skills To Add

```text
harness/skills/client-automation-brief/SKILL.md
harness/skills/control-plane-bootstrap/SKILL.md
harness/skills/context-audit/SKILL.md
```

## Command Prompts To Add

```text
harness/commands/os-client-automation-brief.md
harness/commands/os-control-plane-bootstrap.md
harness/commands/os-context-audit.md
```

## Client Automation Brief Shape

```markdown
# Client Automation Brief

## Outcome
## Current Manual Workflow
## Systems Involved
## Inputs
## Outputs
## Frequency
## Current Time Cost
## Error Cost
## Human Judgment Points
## Must Stay Manual
## Automation Candidate Steps
## Acceptance Criteria
## Approval Gate
## Rollback
## Pilot Scope
## Data Boundaries
## Metrics Baseline
```

## Automation Fit Rules

Good first automation:

- frequent,
- painful,
- visible,
- measurable,
- stable enough to automate,
- low enough risk for a pilot,
- has a clear human approval gate.

Bad first automation:

- high compliance risk without an approval model,
- unstable or undocumented process,
- unclear owner,
- no measurable success,
- requires full system replacement,
- asks for fully autonomous irreversible actions.

## Control Plane Database Shape

At minimum, customer OS control planes need:

| Database | Purpose |
| --- | --- |
| Work Items | Cross-room queue and current state. |
| Runs | Execution history, validation evidence, outputs, and failures. |
| Approvals | Human review queue for risky or customer-visible actions. |
| Activity Log | Event stream that agents and operators can read. |
| Sources | Repositories, folders, Notion pages, Slack channels, dashboards, and tools. |

Queue database rows should include:

```text
Name, Status, Ready, Priority, Owner, Agent, Source, Output URL, Notes, Last Run, Retry Count
```

## Implementation Steps

1. Add customer automation templates under `templates/customer/`.
2. Add control-plane database spec template under `templates/notion/`.
3. Add command prompts for client automation brief, control-plane bootstrap, and context audit.
4. Add skills for brief generation, Notion/control-plane bootstrap, and context audit.
5. Update docs and template index.
6. Extend install validation so fresh installs include the new playbook templates.
7. Add tests that confirm `docs update` installs the templates and preserves local edits.
8. Add examples only after private/client-specific material has been scrubbed.

## Out Of Scope

- Copying Clark's Consulting-specific database IDs into reusable templates.
- Publishing or writing to a customer Notion without explicit workspace verification.
- Building executable customer workers before the workflow, approval gate, and run log exist.
- Pricing guidance beyond the fields needed to capture ROI inputs.

## Acceptance Criteria

- A customer discovery session can produce a client automation brief from installed templates.
- The brief clearly separates deterministic, rule-based, LLM-needed, and human judgment steps.
- The automation-fit matrix prevents premature autonomous builds.
- The control-plane bootstrap spec includes queues, runs, approvals, activity log, sources, and engine-control decisions.
- Customer-facing templates contain no private factory, Clark's Consulting, or course-specific identifiers.

## Validation

- `pytest -q`
- `agentic-os docs update --root <tmp-root>`
- `agentic-os validate --root <tmp-root>`
- Grep reusable templates for private identifiers before customer packaging.
