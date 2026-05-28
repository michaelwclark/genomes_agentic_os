<!--
  Spec produced by the Duel skill (~/.claude/skills/duel/)
  Duel ID:        2026-05-24-4b14606e
  Started:        2026-05-24T19:37:26.470Z
  Ended:          2026-05-24T19:50:07.792Z
  Termination:    PASS
  Final artifact: final-spec.md
  Total rounds:   7
  Total cost:     $0.0000 of $20.00 cap
  Writer:         codex-cli (default)
  Critic:         codex-cli (default)
-->

# OS Update Channel And Fleet Spec v3

## Vision

Genome's Agentic OS needs a deterministic update channel for many installed OS roots across operator and customer environments. The system must make fleet health visible, discover available updates, apply only policy-allowed safe changes automatically, and preserve local/operator work. It must treat customer data as out of scope for telemetry by design, not by convention.

The update model is based on four principles:

1. Every installed OS root has a non-secret installation identity and explicit update policy.
2. Update manifests describe desired package, registry, migration, artifact, and checksum state from a canonical source that is not Notion-only.
3. Automatic apply is limited to deterministic, non-destructive changes where manifest metadata, local file state, and machine-readable policy fields prove no operator edit will be overwritten.
4. Risky, executable, permission-affecting, destructive, customer-visible, or policy-ambiguous changes require an approval gate before apply.

## Architecture

### Installed Root Files

Each managed OS root contains the following files:

```text
~/agentic_os/
  .agentic_root
  agentic-os.package.json
  agentic-os.lock.json
  agentic-os.local.json
  UPDATE_POLICY.md
  registries/
    updates.yml
    capabilities.yml
```

`agentic-os.package.json` declares package identity, installed package versions, manifest source configuration, known registry paths, and schema version. `agentic-os.lock.json` records resolved update state, checksums, last applied manifest, generated-file ownership, rollback runs, and last known update result. `agentic-os.local.json` stores local-only install identity and machine-readable local policy values. `UPDATE_POLICY.md` is both the human-readable policy contract and a required parseable policy artifact. Registry files expose update channels and installed capabilities to agents.

### Installation Identity

Each installed OS root gets a random, non-secret `install_id`. It identifies an installed OS root, not a person, repository, prompt, source tree, or customer document set.

```yaml
install_id: 01HYEXAMPLE0000000000000000
os_name: genomes-agentic-os
channel: stable
installed_version: 0.1.0
customer_id: optional-customer-safe-id
environment: operator | customer
created_at: 2026-05-23T00:00:00Z
```

`customer_id` is optional and must be a customer-approved safe identifier. It must not default to a company name, project name, repository name, email domain, Slack workspace, Notion workspace, or path-derived value.

### Machine-Readable Policy Contract

`UPDATE_POLICY.md` must begin with a canonical YAML frontmatter block. Human-readable prose may follow the frontmatter, but prose is not enforceable policy input. The updater must parse only the frontmatter fields below when evaluating policy consistency.

```yaml
---
schema_version: 1
environment: customer
channel: stable
policy_mode: safe_additive
auto_update_enabled: true
executable_update_policy: approval_required
mcp_update_policy: approval_required
hook_update_policy: approval_required
permission_update_policy: approval_required
customer_approved_id: optional-customer-safe-id
policy_updated_at: 2026-05-23T00:00:00Z
---
```

Required fields are `schema_version`, `environment`, `channel`, `policy_mode`, `auto_update_enabled`, `executable_update_policy`, `mcp_update_policy`, `hook_update_policy`, and `permission_update_policy`. `customer_approved_id` is optional; when present, it must exactly match the safe `customer_id` in `agentic-os.local.json`. Unknown fields are allowed for human process metadata but must not grant permissions. Missing, unparsable, duplicated, type-invalid, unknown-enum, or conflicting required fields make the policy inconsistent.

Allowed enum values:

| Field | Values |
| --- | --- |
| `environment` | `operator`, `customer` |
| `channel` | `dev`, `preview`, `stable`, `pinned` |
| `policy_mode` | `manual_only`, `safe_additive`, `prompt_before_apply`, `pinned_version` |
| `auto_update_enabled` | `true`, `false` |
| executable/MCP/hook/permission policies | `blocked`, `approval_required`, `explicitly_allowed` |

For customer installs, auto-apply is permitted only when `agentic-os.local.json` and `UPDATE_POLICY.md` frontmatter exactly agree on `environment`, `channel`, `policy_mode`, `auto_update_enabled`, and any present `customer_approved_id`. Human prose cannot override these fields. If `UPDATE_POLICY.md` contains only prose, contains conflicting prose, or omits canonical frontmatter, `apply` must fail closed as `pinned_version` even when `agentic-os.local.json` requests `safe_additive`.

### Channels, Defaults, And Policy Precedence

| Channel | Purpose | Auto-Update Default |
| --- | --- | --- |
| `dev` | local operator dogfooding | manual |
| `preview` | early operator/customer pilots | check automatically, apply manually |
| `stable` | normal customer installs with explicit policy | safe additive updates may auto-apply |
| `pinned` | regulated, frozen, or policy-ambiguous installs | no auto-apply |

Default policies when both `agentic-os.local.json` and `UPDATE_POLICY.md` frontmatter are present, parseable, and consistent:

| Environment | Default Channel | Default Policy |
| --- | --- | --- |
| operator | `preview` | `prompt_before_apply` |
| customer | `stable` | `safe_additive` for templates, registries, and docs only |
| regulated customer | `pinned` | `pinned_version` |

Policy precedence is fail-closed for apply:

1. If `.agentic_root`, `agentic-os.local.json`, or `UPDATE_POLICY.md` is missing, unreadable, invalid, unparsable, prose-only, or inconsistent, the effective apply policy is `pinned_version`.
2. In policy-ambiguous state, `check`, `status`, `plan`, and `heartbeat` may run, but `apply` must not write files.
3. A customer install may use `stable` plus `safe_additive` only when the machine-readable local policy and canonical `UPDATE_POLICY.md` frontmatter agree on channel, policy mode, environment, customer-approved id when present, and auto-update setting.
4. Executable updates, hook changes, MCP changes, permission changes, migrations that alter behavior, and destructive changes require explicit policy allowlisting or plan-bound approval even on `stable`.
5. `auto_update_enabled: false` blocks automatic apply regardless of channel or policy mode.

### Phone Home Contract

Heartbeat telemetry sends only operational metadata. The heartbeat builder must construct the payload from allowlisted fields, never from raw logs, project scans, prompts, repository metadata, environment variable maps, file contents, or MCP configuration bodies.

Allowed payload:

```json
{
  "install_id": "01HYEXAMPLE0000000000000000",
  "os_name": "genomes-agentic-os",
  "installed_version": "0.1.0",
  "channel": "stable",
  "capability_hash": "sha256:...",
  "last_update_check": "2026-05-23T00:00:00Z",
  "doctor_summary": {
    "ok": true,
    "blockers": 0,
    "warnings": 2
  }
}
```

Forbidden telemetry fields include prompts, customer documents, source code, environment variable values, MCP tokens, raw logs, project names, absolute paths, Notion page names, Slack channel names, repository names, and customer identifiers that have not been explicitly approved.

A code-level telemetry allowlist must validate the outgoing JSON keys before sending. If any non-allowlisted key is present, heartbeat fails closed, writes a local telemetry violation record, and sends nothing.

### Update Manifest

The canonical update source publishes manifests in JSON. The source may be a Git release artifact, static HTTPS file, or future hosted service. Notion may mirror status for visibility, but it must not be the sole source of truth.

V1 manifest schema:

```json
{
  "schema_version": 1,
  "os_name": "genomes-agentic-os",
  "version": "0.2.0",
  "channel": "stable",
  "released_at": "2026-05-23T00:00:00Z",
  "minimum_supported_version": "0.1.0",
  "manifest_digest": "sha256:manifest-verification-payload-digest",
  "packages": [
    {
      "id": "context-mode",
      "version": "1.2.0",
      "type": "mcp",
      "update_policy": "additive_non_destructive"
    }
  ],
  "files": [
    {
      "id": "registries-capabilities-additions",
      "package_id": "context-mode",
      "operation_intent": "merge_registry_additive",
      "target_path": "registries/capabilities.yml",
      "artifact_uri": "artifacts/registries/capabilities.context-mode.yml",
      "artifact_digest": "sha256:artifact-bytes-digest",
      "content_digest": "sha256:fragment-content-digest-for-merge-or-full-content-digest-for-file-write",
      "content_digest_scope": "artifact_fragment",
      "expected_prior_digest": "sha256:optional-prior-generated-digest",
      "mode": "0644",
      "generated_owner": "agentic-os-update",
      "executable": false,
      "requires_approval": false
    }
  ],
  "migrations": [
    {
      "id": "add-visible-capability-registries",
      "risk": "safe_additive",
      "requires_approval": false
    }
  ],
  "signature": "optional-signature"
}
```

The `files` section is mandatory for every operation that may write, replace, merge, chmod, or delete a file. No file write can be planned unless it is backed by exactly one explicit manifest `files[]` entry. Generic package version changes and migration entries can influence status, but they cannot create write operations unless a matching file entry or migration implementation declares the exact operation metadata required by this spec.

Each file entry must provide a stable `id`, canonical relative `target_path`, artifact source, artifact digest, intended operation class, target mode, executable flag, generated ownership marker, and expected prior digest when replacing generated content. File entries must also declare `content_digest_scope`. For `add_file` and `replace_generated_file`, `content_digest_scope` must be `full_file` and `content_digest` is the digest of the exact post-write bytes. For `merge_registry_additive`, `content_digest_scope` must be `artifact_fragment` and `content_digest` is the digest of the canonical registry fragment being added, not the whole post-merge local registry file. The planner must copy these fields into `update-plan.json` so every write operation is traceable to explicit manifest metadata.

The updater must reject manifests where `os_name`, `channel`, schema version, manifest digest, file digest, artifact digest, digest scope, path validation, mode, executable metadata, or `minimum_supported_version` are incompatible with the installed root. V1 requires checksum verification for all changed artifacts and file writes. Manifest signatures remain an open decision, but the implementation must leave a manifest verification interface so signatures can become mandatory without rewriting the apply flow.

### Manifest Digest And Signature Canonicalization

The manifest digest is computed over a canonical manifest verification payload, not over the raw manifest bytes. The verification payload is the manifest JSON object after removing exactly the top-level fields `manifest_digest` and `signature`, with no other fields removed or rewritten. The remaining object is serialized using RFC 8785 JSON Canonicalization Scheme and hashed with SHA-256. The stored value is encoded as `sha256:<lowercase-hex-digest>`.

Signature verification, when enabled, signs and verifies the same canonical verification payload bytes used for `manifest_digest`. Implementations must not compute digest or signature over pretty-printed JSON, transport bytes, field insertion order, or a payload that keeps either `manifest_digest` or `signature`. A manifest with malformed JSON, duplicate keys, unsupported number forms under RFC 8785, a digest that does not match the canonical verification payload, or a signature over any other byte range is invalid.

This rule makes verification reproducible across implementations and avoids the self-referential digest problem caused by embedding `manifest_digest` inside the manifest it describes.

### Path Safety

All manifest paths are denied unless they pass root containment checks before planning and again before writing:

1. `target_path` must be relative to the OS root and must not begin with `/`, `~`, a drive prefix, or URI scheme.
2. `target_path` must not contain `..`, empty path segments, control characters, shell metacharacter-only segments, or platform-specific absolute path forms.
3. The normalized target must resolve under the OS root after symlink resolution. If any existing path component is a symlink that escapes the root, the operation is denied.
4. Manifest entries must not target `.agentic_root`, `agentic-os.local.json`, `UPDATE_POLICY.md`, secrets, token files, environment files, private keys, or local-only config unless the operation is approval-required and policy explicitly permits that target class.
5. Registry merge targets are restricted to known registry paths declared in `agentic-os.package.json` and lockfile ownership metadata.

Checksum verification never bypasses path safety. A file with a valid digest is still denied if its path is unsafe.

### Registry Additive Merge Semantics

Registry additive merges preserve local registry entries and verify the canonical added fragment, not a manifest-known full-file digest. The artifact for `merge_registry_additive` must be a parseable registry fragment whose canonical serialized form hashes to the manifest `content_digest` with `content_digest_scope: artifact_fragment`.

The merge algorithm is deterministic:

1. Parse the current local registry and artifact fragment with the registry schema for the target registry path.
2. Reject duplicate keys inside the artifact fragment.
3. Reject the merge if any artifact key already exists locally with a different value.
4. Treat artifact keys that already exist locally with identical values as idempotent no-ops.
5. Add only missing artifact keys.
6. Serialize the resulting local registry with the repository's canonical registry serializer.
7. Reparse the serialized output and assert that all pre-existing local keys retain identical values and all artifact keys are present with artifact values.

The plan records the artifact fragment digest, the pre-merge local registry digest, the set of added keys, the set of idempotent keys, and the post-merge local digest computed at plan time. Apply must recompute all of these immediately before writing. If the local pre-merge digest has changed, the additive invariant fails, or the recomputed added/idempotent key sets differ from the plan, the operation is blocked as stale and requires a new plan. This preserves allowed local additions without requiring the central manifest to know every customer registry state.

### Update Plan Generation

`agentic-os update plan` compares local lock state against the resolved manifest and emits `update-plan.json`. The plan classifies each operation as one of:

| Operation Class | Meaning | Auto-Apply Eligible |
| --- | --- | --- |
| `add_file` | create a new file at a safe path that does not exist | yes, if policy permits |
| `replace_generated_file` | replace a file previously generated by an update and checksum matches expected prior state | yes, if policy permits |
| `merge_registry_additive` | add registry entries without deleting or changing existing local entries | yes, if deterministic merge succeeds |
| `modify_local_file` | change a file whose current checksum is unknown or locally edited | no |
| `delete_file` | remove any file | no |
| `change_executable` | add or modify executable, hook, MCP, permission, or command surface | no by default |
| `run_migration` | execute a migration step | only when migration risk and local policy explicitly allow it |

A file is auto-apply eligible only if all of these gates pass:

1. The operation is backed by exactly one manifest `files[]` entry.
2. The manifest target path passes path safety checks.
3. The artifact digest verifies.
4. For `add_file` and `replace_generated_file`, `content_digest_scope` is `full_file` and the exact post-write bytes verify against `content_digest`.
5. For `merge_registry_additive`, `content_digest_scope` is `artifact_fragment`, the artifact fragment digest verifies, and the deterministic additive merge invariants prove no existing local registry key is deleted or changed.
6. The local policy is present, readable, consistent with canonical `UPDATE_POLICY.md` frontmatter, and permits the operation class.
7. `auto_update_enabled` is true in both machine-readable policy sources.
8. One file-state invariant holds: the target path does not exist; the target path exists, is recorded as generated by a prior update, and its current checksum equals the prior generated checksum in `agentic-os.lock.json`; or the target path is a supported registry file and the registry merge is additive with no existing key deleted or changed.

If any gate fails, the plan must require approval or block the operation. This is the deterministic mechanism behind `safe_additive`; it is not a forecast or heuristic.

`update-plan.json` must include operation ids, manifest digest, canonical verification payload digest algorithm, source file entry id, target path, normalized resolved path hash, operation class, artifact digest, content digest, content digest scope, expected prior digest or nonexistence proof, registry merge key sets when applicable, mode, executable flag, approval requirement, policy consistency result, parsed policy frontmatter digest, and rollback behavior.

### Approval Artifact

V1 approval uses a local approval artifact, even if future P3 control planes mirror or countersign it. The artifact authorizes only a specific precomputed plan and never authorizes the updater to recompute, add, or mutate operations.

Approval artifact shape:

```json
{
  "schema_version": 1,
  "install_id": "01HYEXAMPLE0000000000000000",
  "root_id": "sha256:root-identity-digest",
  "manifest_digest": "sha256:manifest-verification-payload-digest",
  "plan_digest": "sha256:update-plan-json-canonical-digest",
  "approved_operation_ids": ["op-001", "op-002"],
  "approver": "operator-entered-identity-string",
  "approved_at": "2026-05-24T00:00:00Z",
  "expires_at": "2026-05-25T00:00:00Z",
  "reason": "short human-readable approval reason"
}
```

`apply` must reject approval if the install id, manifest digest, plan digest, operation ids, or expiration do not match the current plan. Approval unlocks only listed operations already present in the approved plan. It cannot approve arbitrary remote commands, newly downloaded files, operations added after approval, or policy-frontmatter conflicts.

### Apply Flow

1. Read `.agentic_root`, `agentic-os.package.json`, `agentic-os.lock.json`, `agentic-os.local.json`, and `UPDATE_POLICY.md`.
2. Parse and validate `UPDATE_POLICY.md` YAML frontmatter, then compare it to local machine-readable policy.
3. Resolve the configured manifest source for the current channel.
4. Validate manifest schema, OS name, channel, minimum supported version, canonical manifest digest, file metadata, digest scopes, path safety, checksums, and optional signature.
5. Compare package versions, registry hashes, file checksums, and migrations.
6. Generate an update plan with per-operation risk classification, manifest traceability, policy consistency result, approval state, and rollback behavior.
7. Run preflight `agentic-os doctor --json` and block apply if doctor has blockers.
8. Create a rollback run directory and snapshot every file that may be changed.
9. Re-gate the plan immediately before each write by rechecking path safety, file existence, current checksum, artifact digest, content digest or fragment digest, registry additive invariants when applicable, approval artifact, parsed policy frontmatter, local policy, and policy eligibility.
10. Apply eligible safe additive operations.
11. Stop at approval-required operations and record them as pending.
12. Run post-update doctor checks.
13. Write updated lockfile state only after successful writes and doctor completion.
14. Emit local logs and optional control-plane status.

The pre-send re-gate in step 9 prevents a stale plan from overwriting an operator edit made between planning and apply. The repeated policy parse prevents a changed `UPDATE_POLICY.md` from being bypassed by an older plan.

### Rollback

Each update writes:

```text
06-runs-and-logs/updates/<timestamp>/
  update-plan.json
  changed-files.txt
  rollback/
  doctor-before.json
  doctor-after.json
  update-result.json
```

Rollback restores files that were changed by the update and recorded in the rollback snapshot. It must not delete operator-created work unless the file was explicitly created by the update in the same run and recorded as generated in `update-plan.json`. Rollback must refuse to overwrite a post-update local edit unless invoked with an explicit `--force-local-overwrite` flag and a written confirmation token.

### Control Plane

Supported control-plane modes:

| Mode | Role |
| --- | --- |
| Git release manifest | canonical source for shipped versions |
| Static HTTPS manifest | canonical or mirror source for shipped versions |
| Notion database | operator visibility and dashboard mirror only |
| Hosted update service | future fleet visibility and update status collection |

Control-plane writes must use the same redacted heartbeat payload shape. Control-plane failures must not block local check, plan, apply, or rollback unless policy explicitly requires central reporting.

### CLI Surface

```text
agentic-os update check --root ~/agentic_os
agentic-os update plan --root ~/agentic_os
agentic-os update apply --root ~/agentic_os
agentic-os update apply --root ~/agentic_os --approval <approval.json>
agentic-os update rollback --root ~/agentic_os --run <id>
agentic-os update status --root ~/agentic_os
agentic-os update heartbeat --root ~/agentic_os
```

`check` resolves and validates the manifest but does not create a write plan. `plan` writes an inspectable plan and exits non-zero if any required input is missing. `apply` applies only policy-eligible operations unless matching plan-bound approval is supplied. `rollback` restores a prior run snapshot. `status` reports local state for operators and agents. `heartbeat` may phone home and write status, but must never apply updates.

### Doctor Integration

`agentic-os doctor` includes update fields:

- installed version
- update channel
- effective policy mode
- `UPDATE_POLICY.md` frontmatter parse status
- policy consistency status
- auto-update enabled status
- last update check
- pending update version
- pending approval-required operations
- last successful update
- failed update attempts
- rollback availability
- phone-home status
- telemetry policy status
- manifest verification status
- manifest canonicalization status
- path safety validation status

Doctor output must have a JSON mode so automation can summarize it without scraping human text.

## Phases

### P1: Local Update Identity, Manifest Check, Policy Parsing, And Status (1 week)

Deliver installed root identity, schema validation, manifest resolution, file-entry validation, path safety validation, canonical manifest digest verification, canonical `UPDATE_POLICY.md` frontmatter parsing, policy consistency checks, `check`, `status`, and doctor update fields. P1 does not apply updates. It proves the local state model and makes update visibility available to operators and agents.

P1 outputs:

- schemas for package, lock, local identity, update manifest, manifest file entries, `UPDATE_POLICY.md` frontmatter, approval artifact, and heartbeat payload
- RFC 8785 canonical manifest verification payload implementation with `manifest_digest` and `signature` omitted
- `agentic-os update check --root <path>`
- `agentic-os update status --root <path>`
- doctor JSON fields for update status, policy frontmatter parse status, policy consistency, and manifest canonicalization status
- redacted heartbeat payload builder with allowlist validation, but no network sender required

### P2: Deterministic Planning, Safe Additive Apply, And Rollback (2 weeks)

Deliver plan generation from explicit manifest file entries, deterministic operation classification, rollback snapshot creation, safe additive apply, post-update doctor, and lockfile updates. P2 supports local or static manifest sources. P2 must implement pre-write re-gate, checksum-based generated-file ownership rules, path safety checks, canonical policy-frontmatter validation, registry additive merge invariants, and fail-closed missing-policy behavior.

P2 outputs:

- `agentic-os update plan --root <path>`
- `agentic-os update apply --root <path>` for safe additive operations
- rollback run directory creation
- `agentic-os update rollback --root <path> --run <id>`
- pending approval reporting for risky operations
- tests covering stale-plan protection, path denial, manifest traceability, policy-frontmatter ambiguity, registry local-addition preservation, and local-edit preservation

### P3: Fleet Heartbeat, Approval Gates, And Control-Plane Mirror (2 weeks)

Deliver heartbeat sending, plan-bound approval artifact handling, control-plane status mirror, and fleet grouping fields. P3 keeps Notion optional and mirror-only. Hosted service support may be introduced behind an interface, but local update behavior must work without it.

P3 outputs:

- `agentic-os update heartbeat --root <path>`
- approval artifact generation and validation flow for risky changes
- Notion mirror writer if Genome's Notion access is available and configured
- hosted collector interface with static HTTP implementation option
- fleet status summary command or export

## Acceptance Criteria

1. A fresh installed OS root receives a stable non-secret `install_id` and records it in local state without deriving it from customer or project content.
2. `agentic-os update check` validates a compatible manifest and rejects incompatible OS name, channel, schema, checksum, path, file metadata, digest scope, canonicalization, or minimum-version inputs.
3. Manifest digest validation uses exactly RFC 8785 canonical JSON with top-level `manifest_digest` and `signature` omitted before SHA-256 hashing, and rejects any manifest whose embedded digest does not match that payload.
4. If signature verification is enabled, signatures are checked against the same canonical verification payload used for `manifest_digest`.
5. `agentic-os update check`, `status`, and `doctor --json` parse `UPDATE_POLICY.md` frontmatter and report missing, unparsable, prose-only, type-invalid, unknown-enum, or conflicting policy fields as policy-inconsistent.
6. `agentic-os update plan` refuses to create any write operation unless it is backed by exactly one explicit manifest file entry with target path, artifact digest, content digest, content digest scope, operation intent, mode, executable flag, and ownership metadata.
7. `agentic-os update plan` classifies every candidate operation into a concrete operation class and records whether it is auto-apply eligible.
8. `safe_additive` auto-apply writes only files that are new, generated-and-unchanged, or registry-additive under deterministic merge rules.
9. `merge_registry_additive` verifies the artifact fragment digest, preserves all existing local registry keys and values, treats identical existing artifact keys as idempotent, and blocks if an artifact key conflicts with a local value.
10. If local policy is missing, unreadable, invalid, prose-only, unparsable, or inconsistent with `UPDATE_POLICY.md` frontmatter, customer apply fails closed as `pinned_version` while `check`, `status`, `plan`, and `heartbeat` remain available.
11. If a local file changes after planning but before apply, the pre-write re-gate detects the checksum mismatch and blocks that operation.
12. If a local registry changes after planning but before additive merge apply, the pre-write re-gate recomputes registry merge invariants and blocks the operation unless the new state still matches the approved plan's pre-merge digest and key sets.
13. If `UPDATE_POLICY.md` changes after planning but before apply, the pre-write re-gate reparses it and blocks apply when the parsed policy digest or consistency result no longer matches the plan.
14. Customer installs never auto-apply executable, hook, MCP, permission, destructive, or behavior-changing migration operations unless policy explicitly allows them and any required approval is bound to the current plan digest.
15. Heartbeat sends only allowlisted operational metadata and fails closed if a non-allowlisted field is present.
16. Rollback restores changed generated files from the recorded snapshot and refuses to overwrite post-update local edits by default.
17. Notion can mirror update status but local update check, plan, apply, rollback, and status work without Notion.
18. `agentic-os doctor --json` exposes update status fields for agents and operators.

## Validations

Automated validations:

- Unit tests for manifest schema validation and incompatible manifest rejection.
- Unit tests for RFC 8785 manifest canonicalization with `manifest_digest` and `signature` omitted.
- Unit tests that prove digest verification fails when hashing raw manifest bytes, keeping `manifest_digest`, keeping `signature`, or using non-canonical key order.
- Unit tests that assert signature verification, when enabled, uses the same canonical verification payload as manifest digest verification.
- Unit tests that reject manifests with package updates but no explicit `files[]` metadata for writes.
- Unit tests that assert every planned write has source file entry id, target path, artifact digest, content digest, content digest scope, expected prior digest or nonexistence proof, mode, executable flag, and operation class.
- Unit tests for path denial: absolute paths, `..`, symlink escape, local-only config targets, and secret-like files.
- Unit tests for missing, unreadable, invalid, prose-only, unparsable, and conflicting `UPDATE_POLICY.md` frontmatter causing apply to fail closed.
- Unit tests for local policy and `UPDATE_POLICY.md` frontmatter agreement on `environment`, `channel`, `policy_mode`, `auto_update_enabled`, and `customer_approved_id` when present.
- Unit tests for approval artifact digest binding, operation id binding, install id binding, and expiration.
- Unit tests for telemetry allowlist enforcement with forbidden sample keys such as `prompt`, `env`, `path`, `repo`, `raw_log`, and `token`.
- Unit tests for safe additive operation classification.
- Unit tests for registry additive merge idempotency, local addition preservation, conflicting key rejection, and fragment digest verification.
- Integration test where a stale plan is blocked after a file checksum changes.
- Integration test where a stale registry merge plan is blocked after the local registry changes between plan and apply.
- Integration test where apply is blocked after `UPDATE_POLICY.md` changes between plan and apply.
- Integration test where a generated file is replaced only when its current checksum equals lockfile state.
- Integration test where rollback restores changed files and preserves untracked operator-created files.
- CLI golden tests for `check`, `plan`, `apply`, `rollback`, `status`, and `doctor --json` output shapes.

Manual validations:

- Install an operator root on `preview` and confirm apply requires approval by default.
- Install a customer root on `stable` with consistent local policy and `UPDATE_POLICY.md` frontmatter and confirm doc/template additions auto-apply while executable changes remain pending.
- Add a local registry entry before planning a registry additive merge and confirm the merge preserves it.
- Populate a manifest with both `manifest_digest` and `signature` fields and confirm digest verification succeeds only with the defined canonical payload.
- Replace `UPDATE_POLICY.md` frontmatter with prose-only text and confirm apply fails closed while check/status/heartbeat still work.
- Conflict `UPDATE_POLICY.md` channel or auto-update setting against `agentic-os.local.json` and confirm apply fails closed.
- Disable auto-update in `UPDATE_POLICY.md` and confirm heartbeat/check still work while apply is blocked.
- Configure no Notion access and confirm local update commands still succeed.

## Risks

| Risk | Mitigation |
| --- | --- |
| Telemetry accidentally includes sensitive customer context | Build heartbeat from an explicit allowlist and fail closed on unknown keys |
| Safe additive update overwrites local edits | Require explicit manifest file metadata, checksum or path-nonexistence proof, and re-gate before every write |
| Ambiguous policy prose allows unintended customer auto-apply | Require canonical `UPDATE_POLICY.md` frontmatter and fail closed on missing, unparsable, or conflicting fields |
| Manifest digest verification differs between implementations | Require RFC 8785 canonical JSON over the manifest with only `manifest_digest` and `signature` omitted |
| Registry additive merge rejects or overwrites valid local additions | Verify artifact fragment digest and deterministic merge invariants instead of requiring a manifest-known whole-file digest |
| Malicious manifest writes outside the OS root | Require path normalization, symlink containment checks, denied local-only targets, and repeated path validation before write |
| Notion becomes an implicit source of truth | Keep manifest resolution independent and treat Notion as mirror-only |
| Rollback deletes operator work | Snapshot changed files only and require generated-file ownership before deleting update-created files |
| Manifests are tampered with before signature support lands | Require checksum verification in V1 and keep signature verification interface explicit |
| Customer policy is ambiguous | Treat missing, unreadable, invalid, prose-only, unparsable, or conflicting policy as `pinned_version` for apply |
| Approval flow becomes remote command execution | Approval only unlocks listed operations in a local precomputed plan digest; no arbitrary remote commands are accepted |

## What's NOT in v3

- No unmanaged remote command execution.
- No silent exfiltration of prompts, customer documents, source code, secrets, raw logs, paths, repository names, or project names.
- No destructive auto-update by default.
- No dependency on Notion as the only update control plane.
- No mandatory hosted service for local update operation.
- No automatic executable, MCP, hook, permission, local-only config, or behavior-changing migration updates for customer installs without explicit approval or policy allowlisting.
- No write operation derived only from package version metadata, generic checksums, or migration prose.
- No apply when customer policy is missing, unreadable, invalid, prose-only, unparsable, or conflicting.
- No interpretation of free-form `UPDATE_POLICY.md` prose as permission to auto-apply.
- No manifest digest computed over raw JSON bytes, transport bytes, insertion order, or a payload that includes `manifest_digest` or `signature`.
- No requirement that registry additive merge manifests know the final whole-file digest for every customer's locally extended registry.
- No guarantee that manifest signatures are mandatory in V1; checksum verification is mandatory and signature enforcement remains an open decision.

## Open Decisions

- Should V1 require manifest signatures or ship with checksum verification plus a signature interface?
- What is the first heartbeat transport: static HTTP collector, hosted API, or Git-backed status sink?
- How should operator-managed customer fleets group installs: by customer-safe id, environment, channel, or capability bundle?
- Should control-plane approval records be allowed to countersign local approval artifacts after V1, and what trust model should govern them?
