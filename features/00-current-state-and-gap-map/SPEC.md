# 00 Current State And Gap Map

Source card: https://www.notion.so/00-Current-State-And-Gap-Map-366683b48dab8175bcebc1e204696b64

Canonical plan: `/Users/genome/projects/genomes_agentic_os/PLANS/00-current-state-and-gap-map.md`

## Source Spec

The source plan captures the current Genome's Agentic OS position: the repo has a working V1 scaffold, but it does not yet keep rooms alive as a full operating system.

Built CLI surface:

- `agentic-os init`
- `agentic-os domain create`
- `agentic-os workflow create`
- `agentic-os automation create`
- `agentic-os run-log create`
- `agentic-os docs install`
- `agentic-os docs update`
- `agentic-os validate`

Built runtime surface:

- Domain-first installed root at `~/agentic_os`.
- Root and domain routers for Codex, Claude, and generic agents.
- Standard domain lanes for control plane, inbox, projects, workflows, automations, knowledge, runs, metrics, and archive.
- Workflow folder scaffold with PRD, implementation plan, dispatch handoff, context pack, approval rules, output contract, runbook, examples, and runs.
- Automation folder scaffold with trigger, inputs, outputs, permissions, failure modes, runbook, tests, and logs.
- Runtime operating manual, harness commands, harness skills, templates, and SVG diagrams under `shared_factory/05-knowledge/`.
- Additive `docs update` behavior that copies missing managed assets without overwriting existing runtime edits.
- Structural validation for required files, required folders, and parseable JSON/YAML.

Missing operational capabilities include project creation and active-work registration, cwd-aware routing, automatic context pack creation, workflow readiness checks, run closeout, heartbeats, connected-source registries, provider registries, event envelopes and ledgers, automation maturity enforcement, doctor checks, migrations, Notion control-plane sync, and customer OS factory flow.

## Acceptance Criteria

- A fresh agent can read this directory and know what to build next.
- The installed OS contains these plans under `shared_factory/05-knowledge/plans/`.
- Validation requires the plans index and future-ideas plan to exist in the installed runtime.
- Future feature work can be traced back to one plan file.

## Validation

- `uv run pytest -q`
- `uv run agentic-os validate --root ~/agentic_os`
- Confirm `~/agentic_os/shared_factory/05-knowledge/plans/README.md` exists and indexes the backlog.
- Confirm `~/agentic_os/shared_factory/05-knowledge/plans/09-future-ideas-intake.md` exists.
