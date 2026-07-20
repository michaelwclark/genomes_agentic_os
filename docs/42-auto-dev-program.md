# 42 · Auto-Dev Program

> **One SDLC front door:** investigate, author the right artifacts, implement,
> review/repair, release/deploy, and close out—with behavior specialized by
> root, domain, and project Markdown rather than copied workflows.

![Auto-Dev program flow](architecture/diagrams/auto-dev-program.svg)

## Architecture at a glance

| Layer | Owns | Does not own |
| --- | --- | --- |
| Auto-Dev program | intent routing, workflow family, shared policy planes, operator docs and handoffs | a second execution state machine |
| Development Delivery | work items, isolated worktrees, task/portfolio state, retries, receipts, review/release/deploy stages | provider artifact style or domain evidence catalogs |
| Create Artifacts | provider/type policy, native rendering, safety validation, explicit apply/readback | tracker or documentation lifecycle state |
| Detective | version-first evidence gathering, source adapters, hypotheses and RCA | data/config mutation |
| Domain/project packs | exact tech stack, repositories, environments, evidence sources, provider terminology and output requirements | forks of shared workflow code |

## Dynamic policy folders

Adding a Markdown file changes the next run; no Python or registry edit is
needed.

| Behavior | Root | Domain | Project |
| --- | --- | --- | --- |
| Code/review | `harness/shared_factory/05-knowledge/dev_standards/` | `05-knowledge/dev_standards/` | `config/dev_standards/` |
| QA | `harness/shared_factory/05-knowledge/qa_gates/` | `05-knowledge/qa_gates/` | `config/qa_gates/` |
| Gitflow | `harness/shared_factory/05-knowledge/gitflow_topology/` | `05-knowledge/gitflow_topology/` | `config/gitflow_topology/` |
| Artifact output | `harness/artifact-config/<provider>/<type>.md` | `artifact-config/<provider>/<type>.md` | `artifact-config/<provider>/<type>.md` |
| Investigation | `harness/investigation-config/` | `investigation-config/` | `investigation-config/` |

Every resolution records ordered sources and a content fingerprint. Narrower
configuration may specialize behavior but cannot weaken parent safety,
approval, sanitization, target verification, or readback.

## Create Artifacts

![Create Artifacts flow](architecture/diagrams/auto-dev-create-artifacts.svg)

```bash
agentic-os artifacts resolve --provider jira --type bug \
  --domain los --project los_app_los_django --explain
agentic-os artifacts render --provider jira --type bug \
  --domain los --project los_app_los_django \
  --input evidence.yml --output draft.json
agentic-os artifacts validate --artifact draft.json
```

Rendering is local. `apply --execute` either writes a routed filesystem target
atomically or creates an external-provider handoff. A chat agent then uses the
registered provider tool, reads the created/updated result back, and records its
ID and hash. A create response alone is not completion.

## Development policy readback

```bash
agentic-os develop policy <domain> <project> --plane dev_standards --json
agentic-os develop policy <domain> <project> --plane qa_gates --json
agentic-os develop policy <domain> <project> --plane gitflow_topology --json
```

`agentic-os develop start ...` snapshots all three planes into the run's
`effective-policies.json` receipt before dispatch.

## Chat routing

Users do not need to remember Auto-Dev names.

- “Why does this fail only for tenant X in preprod?” → Detective.
- “Make this a Jira bug / Linear initiative / RCA page” → Create Artifacts.
- “Fix/build/implement ticket X” → Auto-Dev over Development Delivery.
- “Review this PR” → the canonical others'-PR adapter.

Commands and skills remain available for precise manual invocation and every
workflow can also run as a sub-workflow or trigger-adapter target.

## Receipts and recovery

Keep the normalized request/evidence, effective policy resolution, decisions,
state/events, validation, external action, readback, and final result. Provider,
VPN, or environment unavailability pauses and resumes the same run. Code,
validation, target, and readback failures remain with their owning stage. Never
restart by deleting state or creating a duplicate external artifact.

## Compatibility and retirement

The maintained overlap ledger is
[`ARCHIVE_SOON.md`](../harness/shared_factory/00-programs/auto_dev/ARCHIVE_SOON.md).
It distinguishes canonical owners, trigger/evidence engines worth keeping, and
duplicated state/formatting/orchestration that can be archived only after parity
and rollback evidence.

## Running from Claude vs Codex

Both harnesses use the same CLI, program/workflow files, policy folders,
receipts, commands, and skills. Only the harness invocation/installation layer
differs. Reinstall/sync shared skills after source changes and validate both
registries before release.
