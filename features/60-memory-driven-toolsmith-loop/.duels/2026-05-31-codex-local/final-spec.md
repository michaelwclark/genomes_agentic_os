<!--
  Spec produced by the Duel skill (~/.claude/skills/duel/)
  Duel ID:        2026-05-31-codex-local
  Started:        2026-05-31T15:14:26.966Z
  Ended:          2026-05-31T15:19:21.287Z
  Termination:    PASS
  Final artifact: final-spec.md
  Total rounds:   3
  Total cost:     $0.0000 of $20.00 cap
  Writer:         codex-cli (default)
  Critic:         codex-cli (default)
-->

# Feature Spec: Memory Driven Toolsmith Loop v1

## Vision

Agentic OS should include a local, auditable self-improvement loop that turns repeated operator friction into reviewable toolsmith work. The loop runs on demand and can be scheduled, reads durable evidence from the installed OS, detects recurring opportunities, and emits structured proposals for skills, commands, workflows, automations, validation checks, tool wrappers, memory rules, reference updates, or numbered feature specs.

The loop is not model training and is not autonomous mutation. In v1, the system may write review reports, proposal records, approval records, and draft artifacts only inside allowlisted installed-OS paths. It must not edit live shared skills, commands, workflows, automations, Notion, shell configuration, harness globals, or source package files during analysis. Promotion creates draft work packets behind an explicit operator command, an approval record bound to exact proposal content, and a validation gate.

Fresh installs should include this workflow by default as a documented shared OS workflow plus a disabled or dry-run schedule target. Existing installed roots should receive managed templates additively through a manifest-driven update process that never overwrites locally modified operator configuration or existing proposals.

## Architecture

### Runtime Surfaces

Source templates install into the canonical installed runtime structure under `harness/shared_factory/`:

```text
harness/shared_factory/00-control-plane/self-improvement.yml
harness/shared_factory/00-control-plane/managed-templates.yml
harness/shared_factory/04-workflows/self-improvement-review.md
harness/shared_factory/05-knowledge/templates/runtime/self-improvement-review.yml
harness/shared_factory/05-knowledge/templates/runtime/self-improvement-proposal.yml
harness/shared_factory/05-knowledge/commands/os-self-improvement.md
harness/shared_factory/05-knowledge/skills/toolsmith-reviewer/SKILL.md
harness/shared_factory/06-runs-and-logs/self-improvement/runs/
harness/shared_factory/06-runs-and-logs/self-improvement/proposals/
harness/shared_factory/06-runs-and-logs/self-improvement/approvals/
harness/shared_factory/06-runs-and-logs/self-improvement/drafts/
```

Older roots with top-level `shared_factory/` are legacy read-only input roots only. The updater must write new managed files into `harness/shared_factory/` and emit a migration plan when legacy references are found. It must never write to top-level `shared_factory/` during this feature.

### Managed Install And Update Semantics

Default install behavior is governed by `managed-templates.yml`. Each managed file entry includes:

```yaml
schema_version: 1
entries:
  - source: templates/runtime/self-improvement.yml
    destination: harness/shared_factory/00-control-plane/self-improvement.yml
    source_version: 1
    source_checksum: sha256:...
    installed_checksum: sha256:...
    merge_policy: create_if_missing|replace_if_managed_unchanged|write_new_on_conflict|manual_only
```

Fresh installs write all managed files and record their checksums. Updates may replace a managed file only when the destination exists and still matches the previous `installed_checksum`. If the destination is missing, the updater may create it. If the destination exists with a checksum mismatch, the updater must not overwrite it; it writes a sibling `.new` file or a migration-plan entry under `harness/shared_factory/06-runs-and-logs/self-improvement/runs/` and reports the conflict. Operator configuration files, proposal files, approval files, and draft files use `manual_only` and are never overwritten by update logic.

### Control Plane

`self-improvement.yml` defines deterministic runtime policy:

- `enabled`: whether scheduled execution is allowed.
- `schedule_mode`: `disabled`, `dry_run`, or `apply_proposals`.
- `evidence_roots`: allowlisted relative paths to scan, rooted under canonical `harness/shared_factory/` unless explicitly marked `legacy_read_only`.
- `external_sources`: disabled by default and configured with explicit source records.
- `proposal_thresholds`: minimum score and confidence required for writes.
- `cooldowns`: type-specific suppression windows.
- `redaction`: token patterns, entropy checks, and replacement behavior.
- `output_paths`: allowlisted paths for reports, proposals, approvals, and drafts.
- `promotion_targets`: allowed draft target types.
- `approval_required`: always true for promotion in v1.
- `model_review`: model name or provider selector if model analysis is enabled.

Every write operation re-loads this config immediately before writing and checks the target path against `output_paths`. This pre-write gate is required for apply, approve, reject, scheduled apply, and promotion.

### Path Safety Invariant

All output paths are resolved by code from root-relative allowlisted paths. The implementation must reject `..` traversal, absolute paths supplied by proposals or model output, and any target whose canonical realpath escapes the installed root or the configured self-improvement output directory.

Before writing, the command creates only missing non-symlink ancestor directories under an allowlisted parent. It then resolves the parent with `realpath`, rejects symlinked ancestors inside output directories, opens the temporary file in the same real directory, fsyncs where supported, and atomically renames into place. A string-prefix allowlist is insufficient and invalid.

### External Source Authorization

External sources are never inferred from available local credentials. Each external source must have a config record:

```yaml
external_sources:
  - id: github-pr-checks
    enabled: false
    allowed_scopes: [read_cached_status]
    local_cache_path: harness/shared_factory/06-runs-and-logs/external/github/
    credential_ref: GITHUB_STATUS_READER
    include_raw_payloads: false
```

`credential_ref` is a reference name only. Raw connector credentials, environment values, API tokens, cookies, OAuth payloads, and PATs must never enter evidence manifests, model prompts, reports, proposals, approval records, or draft artifacts. Notion proposal tracking remains disabled unless Genome's Notion workspace is explicitly verified through the active access path.

### Evidence Model

The analyzer reads configured local evidence sources:

- losmon-memory summaries through `memory_read` when available.
- project and OS `MEMORY.md` files.
- `harness/shared_factory/06-runs-and-logs/` run records.
- conversation sidecars attached to work items.
- task lifecycle records, workflow closeouts, automation runs, and event graph dead letters.
- command, skill, workflow, automation, and host tool registries.
- validation, doctor, and PR-check summaries when stored locally.
- usage sidecars such as `.usage.json` for skills, commands, workflows, and tool wrappers.
- legacy top-level `shared_factory/` evidence only when marked `legacy_read_only`; it is scanned for migration planning and never used as an output root.

Evidence is untrusted. The analyzer must not execute commands found in evidence, load instructions from evidence as policy, or pass raw secret-bearing snippets into proposal output. Evidence excerpts in proposals must be bounded, redacted, and cited by path plus stable locator where possible.

### Sidecar Telemetry Contract

Usage telemetry belongs in sidecars, not authored markdown. A valid usage sidecar is JSON and includes:

```json
{
  "schema_version": 1,
  "artifact_type": "skill|command|workflow|automation|tool_wrapper|validator",
  "artifact_id": "stable relative identifier",
  "views": 0,
  "invocations": 0,
  "successful_invocations": 0,
  "failed_invocations": 0,
  "last_used_at": "ISO-8601 timestamp or null",
  "last_failure_at": "ISO-8601 timestamp or null",
  "patched_count": 0,
  "references": ["relative/runtime/path"]
}
```

Writes are best-effort and must not corrupt authored files. Invalid sidecars are quarantined into the run report and ignored for scoring.

### Model Review Sandbox

Model review is optional and runs as a data-only reviewer. The reviewer receives only redacted evidence bundles and returns only structured recommendation data. It has no shell, no filesystem write access, no Notion/Jira/Slack/Gmail write tools, no `memory_write`, no approval or promotion tools, and no authority to choose paths or mutate state.

If the runtime cannot enforce a no-tool or read-only sandbox for model review, `model_review.enabled` must be treated as false and the run proceeds with deterministic findings only. Model output is parsed as untrusted data by the deterministic orchestrator, schema-validated, redacted again, and either merged into candidates or discarded.

### Review Pipeline

A run follows this deterministic pipeline:

1. Load control-plane config and validate schema.
2. Resolve installed root and allowed evidence roots.
3. Collect evidence manifests without executing evidence content.
4. Redact raw evidence before clustering or proposal rendering.
5. Derive deterministic findings: frequency, recency, repeated failures, duplicate commands, missing templates, invalid sidecars, stale proposals, and cooldown hits.
6. Optionally call the sandboxed model reviewer with redacted evidence bundles.
7. Merge deterministic findings and model recommendations into proposal candidates.
8. Score each candidate using the rubric below.
9. Apply dedupe and cooldown rules.
10. Write a run record in apply mode, or print a report only in dry-run mode.
11. In apply mode, write proposal files only after the current config, current proposal state, canonical path, lock, and redaction gates pass.

Dry-run writes nothing, including run records. Apply mode writes run records and proposal files only under `harness/shared_factory/06-runs-and-logs/self-improvement/`.

### Proposal Schema

Each proposal file uses `self-improvement-proposal.yml` and must include:

- `proposal_id`: deterministic hash from opportunity type, normalized recommendation, and primary evidence locators.
- `schema_version`.
- `created_at`.
- `updated_at`.
- `opportunity_type`.
- `title`.
- `summary`.
- `scope`: `project_local`, `installed_os`, or `source_package_candidate`.
- `evidence`: cited locators, redacted excerpts, timestamps, and signal type.
- `deterministic_findings`: machine-derived facts.
- `model_recommendation`: optional recommendation text.
- `score`: frequency, severity, reuse, confidence, blast radius, staleness, and total.
- `dedupe_key`.
- `cooldown_until`.
- `recommended_artifact`.
- `approval_requirement`.
- `validation_plan`.
- `reference_migration_plan`: required when a shared artifact is proposed to change.
- `redaction_status`.
- `content_hash`: sha256 over canonical proposal content excluding mutable status and audit fields.
- `promotion_status`: `proposed`, `approved`, `drafted`, `rejected`, or `superseded`.
- `approval_record_id`: null unless approved.

A proposal that lacks evidence, validation plan, approval requirement, content hash, or redaction status is invalid and must not be written.

### Approval Integrity

Approval is bound to exact proposal content and target. `approve` creates an approval record under `harness/shared_factory/06-runs-and-logs/self-improvement/approvals/` containing:

```yaml
schema_version: 1
approval_id: sha256:...
proposal_id: ...
proposal_content_hash: sha256:...
approved_target: feature-spec|skill-draft|command-draft|workflow-draft|tool-wrapper-draft|reference-update-plan|doctor-check-draft
approved_at: ISO-8601 timestamp
approver: local_operator|configured_user_id
validation_hash: sha256:...
control_plane_hash: sha256:...
```

`approve` re-loads the current proposal and control plane, re-runs schema validation, redaction, reference-migration-plan enforcement, path checks, and target validation before writing the approval record. `promote` re-loads the current proposal, approval record, and control plane; recomputes the proposal content hash and validation hash; and exits nonzero without writing if either hash differs, the proposal status is not approved, the approved target differs from the requested target, the output path is no longer allowlisted, or validation fails.

Any mutation to proposal evidence, recommendation, score, target, migration plan, validation plan, or summary after approval resets `promotion_status` to `proposed`, clears `approval_record_id`, and requires re-approval. Dedupe evidence appends are proposal mutations and therefore invalidate prior approval.

### Scoring

Scoring is deterministic after evidence extraction. Each dimension is `0-5`, and implementations must use this rubric unless the schema version changes:

| Dimension | 0 | 1-2 | 3-4 | 5 |
| --- | --- | --- | --- | --- |
| Frequency | 0-1 occurrence | 2 occurrences in one source | 3-5 occurrences or 2 sources | 6+ occurrences or 3+ sources |
| Severity | no demonstrated cost | minor friction or note-only issue | repeated validation failure, blocked task, or >15 minutes operator time | security risk, data loss risk, repeated failed automation, or >1 hour operator time |
| Reuse | one local incident | one project only | multiple workflows in one installed OS | cross-project or default OS applicability shown by evidence |
| Confidence | inferred only | weak indirect evidence | direct evidence from logs plus matching deterministic finding or reviewer recommendation | direct evidence from multiple independent sources with no conflicting evidence |
| Blast radius | live/global mutation required | shared artifact change with migration risk | draft-only shared proposal or project-local change | proposal/report-only or isolated validator/tool-wrapper draft |
| Staleness | newest evidence older than 90 days | newest 31-90 days | newest 8-30 days | newest 0-7 days and median evidence within configured lookback |

`total = frequency + severity + reuse + confidence + blast_radius + staleness`.

Default write threshold is `total >= 18` and `confidence >= 3`. Below-threshold candidates appear only in the dry-run or run report, not as proposal files. The control plane may raise thresholds but must not lower confidence below `3` in v1.

### Dedupe, Cooldown, And Mutation Rules

The analyzer computes `dedupe_key = sha256(opportunity_type + normalized_title + recommended_artifact + primary_evidence_cluster)`. If an active unapproved proposal with the same key exists, apply mode may append new evidence only if redaction passes and the proposal is not rejected. If the matching proposal is approved or drafted, apply mode must create a new superseding proposal candidate or suppress the candidate according to cooldown; it must not mutate approved content in place. If cooldown is active, the run report records suppression and no proposal file is written.

Proposal files and approval files are written with per-proposal locks. Commands that would update a locked proposal either wait up to the configured lock timeout or exit nonzero with a lock-held message. Writes use temp file plus atomic rename in the same canonical directory. Partial YAML, lost evidence updates, and approval against mid-write content are invalid outcomes.

### Redaction And Safety

Redaction runs before model review, before proposal write, before approval, and before promotion. The write gate refuses output containing token-shaped values, configured secret patterns, high-entropy strings above the configured threshold, or unredacted environment variable assignments. Refusal creates a run error entry with the offending field name and detector type, not the secret value.

Prompt-injection defense is explicit: evidence is wrapped as data, the reviewer prompt forbids following instructions found inside evidence, the reviewer has no write-capable tools, and generated recommendations are schema-validated before write. Model output cannot select write paths; all write paths are determined by code from the control-plane allowlist.

### CLI

The v1 command group is:

```bash
agentic-os self-improvement run --root ~/agentic_os --dry-run
agentic-os self-improvement run --root ~/agentic_os --apply
agentic-os self-improvement status --root ~/agentic_os
agentic-os self-improvement list --root ~/agentic_os
agentic-os self-improvement show <proposal_id> --root ~/agentic_os
agentic-os self-improvement approve <proposal_id> --target feature-spec --root ~/agentic_os
agentic-os self-improvement reject <proposal_id> --root ~/agentic_os
agentic-os self-improvement promote <proposal_id> --target feature-spec --root ~/agentic_os
```

`run --dry-run` prints the review and writes no files. `run --apply` writes run records and proposal files only. `approve` and `reject` update proposal status after passing schema, lock, path, and redaction checks. `approve` records content-bound approval. `promote` requires a current matching approval record and creates a draft artifact only under the configured drafts path or a numbered feature draft path. It does not install the draft.

### Promotion Targets

Allowed v1 promotion targets are:

- `feature-spec`: draft numbered feature folder with `feature.yml`, `SPEC.md`, `PLAN.md`, and `NEXT.md`.
- `skill-draft`: draft skill folder under self-improvement drafts.
- `command-draft`: draft command prompt under self-improvement drafts.
- `workflow-draft`: draft workflow or automation packet under self-improvement drafts.
- `tool-wrapper-draft`: draft script spec and validation plan under self-improvement drafts.
- `reference-update-plan`: patch plan with target files and review checklist.
- `doctor-check-draft`: validation check spec and fixture plan.

Any proposal that changes a skill, command, workflow, or automation referenced by schedules or other workflows must include `reference_migration_plan` before approval. In v1 this is a plan, not an automatic rewrite.

## Phases

### P1: Schemas, Templates, And Dry Run (1 week)

Build the source templates, managed-template manifest schema, control-plane schema, proposal schema, review workflow, command prompt, reviewer skill, and dry-run CLI. Dry-run must resolve canonical evidence roots, produce deterministic findings, call the sandboxed model reviewer only when configured and enforceable, and print a redacted report without writing files.

### P2: Apply Mode, Dedupe, Safety Gates, And Scheduler Target (1 week)

Add apply mode, run records, proposal writes, dedupe, cooldown, redaction refusal, sidecar telemetry parsing, canonical path checks, atomic writes, per-proposal locks, and default installer/update behavior. Add the disabled or dry-run schedule target to fresh installs and make scheduler integration resilient so one failed analyzer run records failure without aborting the full supervisor tick.

### P3: Approval, Promotion, Validation, And Docs (1 week)

Add list/show/status/approve/reject/promote commands, content-bound approval records, draft artifact generation, reference-migration-plan enforcement, validation checks, temp-root smoke coverage, holdout QA fixtures, and operator docs. Ensure current `~/agentic_os` can receive the workflow after implementation without overwriting local configuration or proposals.

## Acceptance Criteria

- `agentic-os self-improvement run --dry-run` reads configured local evidence and prints a redacted review without writing files.
- `agentic-os self-improvement run --apply` writes run records and proposal files only under `harness/shared_factory/06-runs-and-logs/self-improvement/`.
- A fresh install includes the workflow, control-plane config, managed-template manifest, command, reviewer skill, templates, schemas, run/proposal/approval directories, and a disabled or dry-run schedule target.
- Updates write missing managed files, replace only unchanged managed files, and create `.new` or migration-plan output on checksum conflict without overwriting local configuration, proposals, approvals, or drafts.
- Every proposal includes evidence references, opportunity type, score, recommended artifact, approval requirement, validation plan, redaction status, content hash, and promotion status.
- Approval records bind approver marker, approval time, target, proposal content hash, validation hash, and control-plane hash.
- Promotion exits nonzero and writes nothing if proposal content, validation result, approval target, or current output allowlist differs from the approved state.
- Proposals distinguish deterministic findings from model-generated recommendations.
- Model review runs with no write-capable tools; if that sandbox cannot be enforced, model review is disabled.
- The analyzer refuses to write proposals containing token-shaped or configured secret values.
- Duplicate proposals are merged or suppressed within configurable cooldown windows, and approved proposals are not mutated in place by dedupe.
- Scheduled execution integrates with the runtime supervisor without one analyzer failure aborting the full supervisor tick.
- Promotion requires an approved proposal and creates only draft artifacts in allowlisted paths.
- Shared-artifact proposal approval fails unless a reference migration plan is present.
- Validation fails when required templates, schemas, schedule target, command, skill, workflow files, or managed-template entries are missing.
- Top-level legacy `shared_factory/` paths are never written by run, apply, approve, reject, promote, install, or update.
- Tests cover dry-run, apply, dedupe, cooldown, redaction, invalid sidecars, approval invalidation, promotion, scheduler integration, managed-template conflicts, path traversal, symlink escape, and concurrent apply/approve behavior.

## Validations

- Unit tests for proposal scoring rubric bands, deterministic dedupe key generation, cooldown handling, redaction detectors, canonical path allowlist checks, symlink rejection, approval content-hash computation, and sidecar parsing.
- CLI tests for `run --dry-run`, `run --apply`, `status`, `list`, `show`, `approve`, `reject`, and `promote`.
- Schema tests for `self-improvement.yml`, `managed-templates.yml`, review run records, proposal files, approval records, and sidecar telemetry.
- Approval integrity test: approve a valid proposal, then mutate the proposal, output allowlist, validation plan, or requested target before promote; each case must exit nonzero and create no draft.
- Concurrency test with overlapping scheduled apply and manual approve/promote proving locks prevent partial YAML, lost updates, and stale approvals.
- Scheduler integration test proving a failed analyzer run records failure and returns control to the supervisor.
- Temp-root smoke test: run `runtime init`, verify default files exist, seed evidence, run dry-run, run apply, approve one proposal, promote it to a draft feature folder, assert legacy top-level `shared_factory/` was not written, and run `validate`.
- Holdout QA fixtures with noisy logs, prompt-injection text, secret-shaped strings, duplicate evidence, stale evidence, malformed sidecars, low-confidence recommendations, legacy top-level `shared_factory/` references, symlinked proposal directories, and locally modified managed files.

## Risks

- Prompt injection from logs or memory could steer generated proposals.
- Secret-bearing evidence could leak into proposal files or model prompts.
- Overeager scoring could create proposal churn.
- One-off mistakes could become global recommendations.
- Operators could misunderstand the default install as autonomous self-mutation.
- Legacy installed roots could cause writes into ambiguous paths.
- Model recommendations could appear more authoritative than deterministic evidence supports.
- Approval could become stale if proposal content changes after review.
- Concurrent scheduled and manual commands could corrupt proposal state without locks.
- Managed default install files could overwrite local operator edits without conflict semantics.

## Mitigations

- Treat all evidence as untrusted data and never execute or obey evidence content.
- Run redaction before model review, before proposal write, before approval, and before promotion.
- Run model review only in a no-tool or read-only sandbox; otherwise disable it.
- Use code-owned allowlisted output paths, canonical realpath checks, symlink rejection, and re-gate immediately before every write.
- Use atomic writes and per-proposal locks for all proposal and approval mutations.
- Bind approval records to proposal content hash, validation hash, target, and control-plane hash.
- Keep default schedule posture disabled or dry-run.
- Require approval before promotion and keep promotion limited to drafts.
- Require evidence citations, deterministic findings, and validation plans in every proposal.
- Suppress duplicate and cooldown-active proposals, and never mutate approved proposals in place through dedupe.
- Prefer project-local scope unless evidence proves cross-project reuse.
- Emit migration plans for legacy paths and shared artifact references instead of silently rewriting them.
- Use managed-template checksums and conflict outputs instead of overwriting local edits.

## What's NOT in v1

- No model training or hidden model-level learning.
- No autonomous edits to live Claude, Codex, Cursor, Notion, shell configuration, global harness config, shared skills, shared commands, workflows, or automations.
- No unreviewed writes to Genome's Notion or any other workspace.
- No direct archiving, rewriting, or consolidation of live shared artifacts.
- No automatic migration of legacy `shared_factory/` paths.
- No writes to top-level legacy `shared_factory/` paths.
- No private external source ingestion unless explicitly configured and authorized through `external_sources`.
- No raw connector credentials, environment token values, or OAuth payloads in evidence manifests, prompts, reports, proposals, approvals, or drafts.
- No model reviewer with write-capable tools.
- No installation of generated tools, skills, commands, workflows, automations, or validators.
- No replacement of losmon-memory, context-mode, or existing feature/spec workflows.
