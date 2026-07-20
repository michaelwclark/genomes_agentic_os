# Program: Auto-Dev

![Auto-Dev program flow](assets/auto-dev-program.svg)

> **Outcome:** one polymorphic SDLC program—from signal or idea to verified
> evidence, excellent artifacts, production-quality implementation, clean
> review, release/deployment proof, and durable closeout.

Operator documentation: [Auto-Dev — Canonical SDLC Program](https://www.notion.so/3a3683b48dab81b88875f5ec875dab3e)
in Genome's Notion. Local definitions and typed receipts remain authoritative.

## How the pieces fit

Auto-Dev is the operator-facing family. `development_delivery` remains its
durable execution engine for work items, worktrees, state transitions, failure
classification, receipts, and cleanup. Create Artifacts owns provider/type
quality. Detective owns evidence-first diagnosis. Domain/project Markdown files
specialize each workflow without forking shared code.

## Workflow map

| Order | Workflow | Use it for | Manual entrypoint | Terminal handoff |
| --- | --- | --- | --- | --- |
| 0 | Detective | bug, QA/log/alert/ticket-comment analysis and RCA | `/auto-dev-detective` | evidence packet or investigation report |
| 0 | Create Artifacts | Jira/Linear/Notion/Confluence/GitHub/Slack/filesystem output | `/auto-dev-create-artifacts` | validated draft or read-back artifact |
| 1 | Readiness and Context | claim, grooming, evidence and plan | `/auto-dev-readiness` | `planned` |
| 2 | Isolated Implementation | work item/worktree/code/local checks | `/auto-dev-implementation` | `local_validation` |
| 3 | Testing, Review, and PR Repair | test triangle, opposing review, CI/review loops | `/auto-dev-review-repair` | `ready_for_merge` |
| 4 | Release Propagation | required target branches/release PRs | `/auto-dev-release-propagation` | propagation receipt |
| 5 | Merge, Deployment, and Cleanup | merge/deploy/readback/retention | `/auto-dev-closeout` | `delivery_complete` |

Detective and Create Artifacts may run independently, before ticket creation,
or as sub-workflows. A full Auto-Dev run invokes them when evidence or external
artifacts are needed.

## Polymorphic behavior

The shared engine does not contain LOS, Kanga, Jira, Linear, Django, or Vue
defaults. It composes Markdown at runtime:

```text
root policy -> domain additions -> project additions -> invocation overlay
```

Use `artifact-config/` for provider/type output, `investigation-config/` for
Detective sources and environment authority, and the development `05-knowledge`
policy planes for code, QA, and gitflow. Adding a Markdown file affects the next
run and is visible in the effective fingerprint receipt.

## Invocation model

- **Implicit chat route:** intent phrases in `ROUTER.md` select the workflow.
- **Manual:** every workflow exposes a named command/skill and resumes the same
  task state/run packet.
- **Sub-workflow:** programs pass explicit evidence and receipt references.
- **Trigger adapter:** schedules/queues may start a run but do not own its state.

## Run evidence

Each run keeps an immutable request/snapshot, effective policy source list and
fingerprint, state/event ledger, decisions, validation, provider actions,
readback, final result, and unresolved gaps. Raw evidence follows routed
retention; compact receipts survive closeout.

Development stage skills perform provider, code, test, review, merge, and
deployment work. `agentic-os develop stage` is deliberately only a recorder:
it accepts a complete set of `development-stage-evidence/v1` receipts, validates
them before the first transition, and never turns an assertion into an action.

## Failure model

Classify failures before retrying. Provider/VPN/environment unavailability
pauses and resumes from the same receipt. Code, test, validation, target, or
readback failures stay with the owning workflow. Missing product/security/
architecture decisions block with one exact owner action. Never restart by
deleting state or create duplicate external artifacts to escape a pause.

## Program health

Healthy means: routing selects the intended workflow, effective policies are
explainable, every active run advances or names a blocker, external effects have
readback, stale/duplicate compatibility surfaces are shrinking, and a fresh
agent can resume from receipts without chat history.

See `ARCHIVE_SOON.md` for overlap disposition and `runbook.md` for operation.
