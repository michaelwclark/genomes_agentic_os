# Plan

## Pre-Implementation State

Done:

- Hermes-agent research was folded into the packet.
- Feature 60 was reframed as a default-installed shared workflow plus a
  disabled-or-dry-run schedule target.
- The pre-implementation duel passed in 3 rounds with local Codex-only runners.
- The PASS artifact was folded into `SPEC.md`; this file now tracks the build
  phases from that reviewed spec.

## P1: Schemas, Templates, And Dry Run

Build the smallest useful slice first:

- Add source templates for:
  - `harness/shared_factory/00-control-plane/self-improvement.yml`
  - `harness/shared_factory/00-control-plane/managed-templates.yml`
  - `harness/shared_factory/04-workflows/self-improvement-review.md`
  - `harness/shared_factory/05-knowledge/templates/runtime/self-improvement-review.yml`
  - `harness/shared_factory/05-knowledge/templates/runtime/self-improvement-proposal.yml`
  - `harness/shared_factory/05-knowledge/commands/os-self-improvement.md`
  - `harness/shared_factory/05-knowledge/skills/toolsmith-reviewer/SKILL.md`
- Add schema validation for the control plane, managed-template manifest,
  proposal files, run records, approval records, and sidecar telemetry.
- Add `agentic-os self-improvement run --root <root> --dry-run`.
- In dry-run, resolve canonical evidence roots, redact bounded evidence,
  derive deterministic findings, score candidates, and print a review without
  writing any files.
- Treat model review as disabled unless a no-tool or read-only sandbox can be
  enforced.
- Include the self-improvement templates in fresh installs without overwriting
  local operator configuration.

## P2: Apply Mode, Dedupe, Safety Gates, And Scheduler Target

- Add `run --apply`, run records, proposal writes, dedupe, cooldowns,
  redaction refusal, invalid-sidecar quarantine, and per-proposal locks.
- Enforce canonical realpath allowlists, symlink rejection, same-directory temp
  file plus atomic rename writes, and immediate pre-write config reload.
- Add managed-template checksum semantics:
  create missing files, replace unchanged managed files, and write `.new` or a
  migration-plan entry on checksum conflict.
- Add the disabled-or-dry-run schedule target and integrate it with the runtime
  supervisor so analyzer failure records failure without aborting the full tick.

## P3: Approval, Promotion, Validation, And Docs

- Add `status`, `list`, `show`, `approve`, `reject`, and `promote` commands.
- Bind approval records to proposal content hash, validation hash, approved
  target, approver marker, approval time, and control-plane hash.
- Reset approval when proposal evidence, recommendation, score, target,
  validation plan, migration plan, or summary changes.
- Promote only approved proposals, and create draft artifacts only under
  configured draft paths.
- Require `reference_migration_plan` before approving shared-artifact changes.
- Add operator docs and temp-root smoke tests proving fresh install,
  dry-run, apply, approval, promotion, validation, and no writes to legacy
  top-level `shared_factory/` paths.

## Verification Focus

- Unit tests: scoring rubric, dedupe key generation, cooldowns, redaction,
  canonical path checks, symlink rejection, approval hash computation, sidecar
  parsing, and managed-template conflicts.
- CLI tests: dry-run writes nothing; apply writes only run/proposal records;
  approval invalidation blocks promotion; shared-artifact approval requires a
  migration plan.
- Holdout QA: noisy logs, prompt-injection text, token-shaped strings,
  duplicate/stale evidence, malformed sidecars, legacy references, symlinked
  output directories, local managed-file edits, and concurrent apply/approve.
