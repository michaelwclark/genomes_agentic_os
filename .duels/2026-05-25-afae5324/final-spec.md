<!--
  Spec produced by the Duel skill (~/.claude/skills/duel/)
  Duel ID:        2026-05-25-afae5324
  Started:        2026-05-25T21:36:56.926Z
  Ended:          2026-05-25T21:56:22.339Z
  Termination:    PASS
  Final artifact: final-spec.md
  Total rounds:   7
  Total cost:     $0.0000 of $20.00 cap
  Writer:         claude-cli (opus)
  Critic:         codex-cli (default)
-->

# OS Update Channel and Customer Fleet — v3

## Vision

Genome's Agentic OS will be installed in many places: operator workstations, customer laptops, customer servers, and disposable VMs spun up by build-runners. Each install is a hand-edited tree on disk. We need a way to: (a) know what versions are running where, (b) ship safe updates without breaking customer-local work, (c) refuse to leak customer data while doing so, and (d) recover when an update goes wrong.

The update model is **manifest-pull, not push**. Installs read a manifest from a canonical source on a schedule they control. The control plane never opens a connection into a customer install. **Telemetry is default OFF on every customer install.** It is enabled only when `UPDATE_POLICY.md` frontmatter explicitly sets both `telemetry_enabled: true` and `heartbeat_url`; channel selection alone is NOT opt-in. When enabled, telemetry has a fixed schema, is redacted by construction (a schema validator, not a regex pass), and bounded in size.

Risky changes never auto-apply on customer roots without an explicit, bound approval. The risky set is broad on purpose: executables, hooks, MCP configs, permission grants, **and agent rules, instructions, skills, schemas, and behavior-driving registries**. Risky items can only be applied — automatically or manually — when an approval artifact (signed token from the operator OR a `permits:` entry in `UPDATE_POLICY.md`) names the migration id AND the manifest SHA AND the install/customer id AND the risk category AND is unexpired. The evaluator's job is to deterministically promote such an item from `REQUIRES_APPROVAL` to `APPROVED_APPLY`; nothing else may.

Customer auto-apply requires a trust anchor on the manifest source: either (a) an ed25519-signed manifest verified against an `operator_pubkey` pinned in `agentic-os.package.json`, or (b) a manifest fetched from a git tag whose expected SHA is pinned in `agentic-os.lock.json` AND the install has opted into `trust_mode: sha_pinned`. Manifests that satisfy neither yield TrustEvidence `untrusted` and the executor refuses to apply — plan can still be inspected.

The v1 milestone is: an operator can see a dashboard of installed fleet state, ship a safe-additive update to all stable-channel customers without operator action per-install (via the opt-in autoapply job), ship a risky migration to a chosen subset of customers by issuing per-install signed approval tokens that the autoapply job consumes, and roll any install back to the prior version in one CLI command using state stored on disk on that install.

## Architecture

### Layout (installed root)

```
~/agentic_os/
  .agentic_root                       sentinel; absence ⇒ refuse all update ops
  agentic-os.package.json             pinned package + channel + install_id + operator_pubkey (P3+) + trust_mode
  agentic-os.lock.json                installed packages, versions, checksums, source manifest URL + pinned SHA
  agentic-os.local.json               operator/customer overrides; NEVER overwritten by updates
  UPDATE_POLICY.md                    human-readable + machine-parseable frontmatter (incl. permits:)
  registries/
    updates.yml                       channel, policy, last_check, last_apply, optional heartbeat_url
    capabilities.yml                  declared capabilities (drives capability_hash)
    approvals/                        signed approval tokens (P3+), one per migration id
  06-runs-and-logs/updates/<ts>/      one dir per apply attempt; never deleted by update code
```

### Component boundaries (factories, ports)

```
types/update.types.ts            UpdateManifest, UpdatePlan, ApplyResult, PolicyDecision, TrustEvidence (discriminated unions)
adapters/manifest.http.adapter.ts   fetch + verify signed manifest from HTTPS; emits TrustEvidence
adapters/manifest.git.adapter.ts    fetch from git tag of source repo; verify pinned SHA; emits TrustEvidence
adapters/telemetry.https.adapter.ts POST redacted heartbeat
adapters/telemetry.noop.adapter.ts  default whenever telemetry_enabled != true OR heartbeat_url absent
ports/manifest.port.ts            ManifestPort.fetch(channel) → { manifest, trust: TrustEvidence }
ports/telemetry.port.ts           TelemetryPort.send(HeartbeatPayload) — schema enforced at port boundary
data/update/
  update.types.ts                 PlanItem variants (see Risky Change Taxonomy)
  policy.evaluator.ts             pure: (PlanItem[], Policy, UPDATE_POLICY.md frontmatter, TrustEvidence, Approvals[]) → PolicyDecision per item; promotes REQUIRES_APPROVAL → APPROVED_APPLY iff binding matches exactly
  plan.builder.ts                 pure: (lock, manifest, fs-state) → UpdatePlan including per-path pre-state record
  redactor.ts                     pure: (RawHeartbeat) → HeartbeatPayload | RedactionError; schema-constructed
  rollback.snapshot.ts            copy-before-write OR absence tombstone; SHA-pinned manifest of pre-state
  apply.executor.ts               applies one PlanItem at a time inside a write-lock; refuses any item whose decision is not AUTO_APPLY or APPROVED_APPLY; refuses ALL items if TrustEvidence == untrusted on non-dev
  heartbeat.service.ts            builds + sends Heartbeat; never applies
  notify.service.ts               writes pending-update notification; never applies
jobs/update.heartbeat.job.ts      scheduled per channel; checks, writes notification, sends heartbeat if enabled; NEVER applies
jobs/update.autoapply.job.ts      OPT-IN; scheduled only if UPDATE_POLICY.md sets autonomous_apply: true; applies a plan only if EVERY PlanItem's decision ∈ {AUTO_APPLY, APPROVED_APPLY}
init/                             composition root: wires adapters by channel, policy, telemetry flag, and autonomous_apply flag
```

**Layer rule:** `data/update/` never imports `adapters/` directly; manifest and telemetry come through ports. Tests pass fake ports; no network in unit tests.

### Risky Change Taxonomy

PlanItem is a discriminated union. The plan builder assigns the type by path-glob rules declared in the package manifest plus content sniffing (executable bit, shebang). **Unrecognized paths default to the strictest applicable category — there is no "unknown ⇒ additive" fallback.**

| Type | Examples | Default on customer (safe_additive) |
| --- | --- | --- |
| `additive_file` | new template, new doc, new fixture under a known-additive glob | AUTO_APPLY |
| `overwrite_file_generated` | regenerated artifact previously written by update | AUTO_APPLY only if on-disk SHA matches the prior manifest's expected SHA (no local drift) |
| `exec_change` | shell scripts, CLI binaries, hook bodies | REQUIRES_APPROVAL |
| `hook_change` | git hooks, claude hooks, pre-commit | REQUIRES_APPROVAL |
| `mcp_change` | MCP server config, MCP wiring | REQUIRES_APPROVAL |
| `permission_change` | allowlist rules, capability grants, autonomous_apply flag, operator_pubkey | REQUIRES_APPROVAL |
| `rule_change` | CLAUDE.md, AGENTS.md, MEMORY.md, project rule files | REQUIRES_APPROVAL |
| `instruction_change` | prompt files, persona files, skill instructions | REQUIRES_APPROVAL |
| `skill_change` | additions or edits under `skills/` | REQUIRES_APPROVAL |
| `schema_change` | manifest schema, lockfile schema, telemetry schema, frontmatter schema | REQUIRES_APPROVAL |
| `behavior_registry_change` | registries/capabilities.yml, registries/updates.yml, any registry that drives agent dispatch | REQUIRES_APPROVAL |
| `migration` | named script | REQUIRES_APPROVAL |

A single PR adding a new file category MUST add both a glob rule and a paired evaluator test asserting the customer-default decision; CI lints for any path that classifies as `unknown`.

### Deterministic policy evaluator

The policy evaluator is the trust gate. It is a pure function with no I/O. Given a list of PlanItems, the active `Policy`, the parsed `UPDATE_POLICY.md` frontmatter, the manifest's `TrustEvidence`, and the on-disk approval artifacts, it returns one `PolicyDecision` per item.

`PolicyDecision` is a closed discriminated union with exactly four variants:

- `AUTO_APPLY` — item type is in the channel's auto-apply set AND `TrustEvidence ∈ {signed, sha_pinned}` AND no drift detected.
- `APPROVED_APPLY { approval_ref: { artifact_path, kind: signed_token | policy_permit, expires_at } }` — item type would otherwise be `REQUIRES_APPROVAL`, AND `TrustEvidence ∈ {signed, sha_pinned}`, AND an approval artifact exists whose fields all match exactly (see Approval artifact contract). This decision is **terminal**: the executor treats `APPROVED_APPLY` and `AUTO_APPLY` identically for the purpose of "may this item proceed?".
- `REQUIRES_APPROVAL { reason, approval_kind: signed_token | policy_permit, required_binding: { migration_id, manifest_sha, install_or_customer_id, risk_category } }` — emitted ONLY when no approval artifact is present at all. Used by `update plan` to tell the operator what to ask for. The executor refuses items with this decision.
- `BLOCKED { reason }` — used when `TrustEvidence == untrusted`, lockfile `minimum_supported_version` unmet, hard `pinned_version` policy, OR an approval artifact IS present but fails any binding check (mismatched SHA/category/target/expiry, missing/invalid signature where required). The executor refuses items with this decision. **A present-but-mismatched approval never silently degrades to `REQUIRES_APPROVAL`; it is always `BLOCKED` so the failure is loud.**

Promotion rule (the only path from risky to applicable):

```
type = risky AND TrustEvidence ∈ {signed, sha_pinned} AND approval present AND all bindings match AND not expired AND signature valid where required
  ⇒ APPROVED_APPLY
type = risky AND approval present AND any binding/signature check fails
  ⇒ BLOCKED (never APPROVED_APPLY, never REQUIRES_APPROVAL)
type = risky AND no approval present
  ⇒ REQUIRES_APPROVAL
```

The apply executor (and the autoapply job's plan-wide gate) accepts items whose decision is `AUTO_APPLY` OR `APPROVED_APPLY`, and refuses everything else.

### Approval artifact contract

There are exactly two artifact kinds, with different signature rules tuned to phase capability:

- `signed_token` — file under `registries/approvals/<migration_id>.token`. **Always requires** a valid ed25519 signature against `operator_pubkey` from `agentic-os.package.json`. Only available P3+ (when token issuance/verification ships). An install with no `operator_pubkey` set cannot consume `signed_token` artifacts; they evaluate to `BLOCKED { reason: "approval_unsigned" }`.
- `policy_permit` — a `permits[]` entry in `UPDATE_POLICY.md` frontmatter. **Signature is conditional**: REQUIRED iff `agentic-os.package.json` sets `operator_pubkey`; OPTIONAL (and the `signature` field may be absent) when `operator_pubkey` is unset. This is the only approval path available in P1, where `operator_pubkey` is intentionally unset on every install.

Every approval artifact (regardless of kind) MUST contain:

```yaml
migration_id: add-visible-capability-registries
manifest_sha: sha256:abc...           # exact SHA of the manifest this permit applies to
install_id: 01HY...                   # OR customer_id: cust_... ("*" only allowed for operator-root permits)
risk_category: behavior_registry_change
expires_at: 2026-06-30T00:00:00Z       # required; max 90 days from issuance in v1
signature: <ed25519 over the above>    # required for signed_token; for policy_permit, required iff operator_pubkey is set
```

Evaluator rules (all are BLOCKED, not warnings, when an artifact is present but malformed/mismatched):
- Missing or expired `expires_at` ⇒ `BLOCKED { reason: "approval_expired" }`.
- `manifest_sha` mismatch with the manifest under evaluation ⇒ `BLOCKED { reason: "approval_for_different_manifest" }`.
- `risk_category` mismatch with the PlanItem type ⇒ `BLOCKED { reason: "approval_wrong_category" }`.
- `install_id`/`customer_id` mismatch ⇒ `BLOCKED { reason: "approval_wrong_target" }`.
- `signed_token` with missing/invalid signature ⇒ `BLOCKED { reason: "approval_unsigned" }`.
- `policy_permit` with missing/invalid signature WHEN `operator_pubkey` is set ⇒ `BLOCKED { reason: "approval_unsigned" }`.
- `policy_permit` with no signature WHEN `operator_pubkey` is unset ⇒ valid (P1 mode).

**P1 unsigned-permit mode** is the bootstrap configuration. P1 installs MUST NOT have `operator_pubkey` set in `agentic-os.package.json`; setting `operator_pubkey` is itself a `permission_change` requiring approval, so the upgrade P1→P3 is gated. Once `operator_pubkey` is set, all approval artifacts (both kinds) require valid signatures from then on. There is no in-between mode that accepts unsigned permits while a key is present.

When every field matches exactly and the artifact is unexpired (and validly signed where required), the evaluator promotes the PlanItem to `APPROVED_APPLY` and records `approval_ref` pointing at the artifact path. The executor records the same `approval_ref` in `decisions.json` so the post-hoc audit trail names which artifact authorized each risky write.

Doctor surfaces approaching-expiry permits as warnings; the apply executor treats expired or mismatched permits as blockers, not warnings. This binds each approval to one manifest SHA: re-issuing for a new SHA is one CLI command.

### Redactor as schema, not filter

`HeartbeatPayload` is a Zod schema with a closed set of fields (install_id, os_name, installed_version, channel, capability_hash, last_update_check, doctor_summary{ok,blockers,warnings}, optional customer_id). The redactor builds a payload by **constructing from named fields**, never by copying or stripping. Any field not in the schema cannot be in the payload because nothing in the redactor reads from arbitrary maps. The telemetry adapter re-validates the payload against the schema before sending and rejects on extra keys (`.strict()`). A unit test fuzzes the redactor with payloads containing prompts, env values, and file paths and asserts none appear in the output.

A leak now requires modifying both the schema and the constructor in the same PR, which a CI test will catch.

### Apply executor: ordered, idempotent, rollback-first

1. Acquire `registries/.update.lock` (file lock; refuse concurrent applies).
2. Verify `TrustEvidence` from manifest port. If `untrusted` on a non-`dev` channel ⇒ exit code 12 BEFORE evaluating items.
3. Run the evaluator across the whole plan once. If ANY item's decision ∉ {AUTO_APPLY, APPROVED_APPLY}, refuse the whole apply (exit non-zero; for the autoapply job, write `blocked.json` listing each rejected item's reason). No partial application.
4. Snapshot pre-state for every path the plan will touch:
   - Path exists pre-apply: copy bytes to `06-runs-and-logs/updates/<ts>/rollback/<rel-path>` and record `{exists: true, sha, mode, mtime}` in `manifest.sha256.json`.
   - Path does not exist pre-apply: record `{exists: false}` — the **absence tombstone**. No bytes copied.
5. For each PlanItem in plan order: **re-evaluate policy** (defense in depth — the on-disk approval set must still permit the item at write time), apply, write a per-item result record with the post-apply SHA AND the recording `approval_ref` (if APPROVED_APPLY). On any failure: stop, run rollback, exit non-zero.
6. Write `agentic-os.lock.json` LAST. The lock write is the commit point — if power fails before, the next `update apply` sees the old lock and replays cleanly because every file write was preceded by a snapshot record.
7. Release lock; run post-doctor; emit notification (and heartbeat if enabled).

### Rollback semantics

`update rollback --run <id>` reads the run's `manifest.sha256.json` and for each entry:
- Pre-state `{exists: true, sha}` ⇒ restore snapshot bytes.
- Pre-state `{exists: false}` ⇒ delete the file **only if** the file's current SHA matches the post-apply SHA recorded for that PlanItem. If the file has been modified since (operator edited it), leave it in place and report as `preserved_local_edit` in the rollback summary.

This makes rollback safe in two ways: it cannot delete operator-created files at colliding paths (those have no recorded post-apply SHA), and it cannot delete update-created files the operator has since modified.

### Channels and defaults

| Channel | Default Policy (operator root) | Default Policy (customer root) | Telemetry Default |
| --- | --- | --- | --- |
| `dev` | manual_only | (not allowed on customer) | OFF |
| `preview` | prompt_before_apply | manual_only | OFF (opt-in via UPDATE_POLICY.md) |
| `stable` | prompt_before_apply | safe_additive (notification only — see autonomous mode) | OFF (opt-in via UPDATE_POLICY.md) |
| `pinned` | pinned_version | pinned_version | OFF |

Customer installs default to `stable`. Telemetry is OFF on every channel until UPDATE_POLICY.md frontmatter contains BOTH:

```yaml
telemetry_enabled: true
heartbeat_url: https://...
```

Without both keys, init wires `telemetry.noop.adapter.ts`; no network request is made.

### Heartbeat vs apply: two jobs, never one

- `jobs/update.heartbeat.job.ts` — runs on the channel's cadence (preview=daily, stable=hourly, dev/pinned=never). Each run: fetch manifest, run plan builder, write a **notification record** at `06-runs-and-logs/updates/<ts>/pending.json`, and (if telemetry enabled) send the heartbeat. **Never applies anything.**
- `jobs/update.autoapply.job.ts` — only scheduled by init wiring when `UPDATE_POLICY.md` declares `autonomous_apply: true`. Each run: read latest `pending.json`, re-fetch the manifest and the on-disk approval set, run the evaluator, then call the apply executor with the plan-wide gate: every PlanItem's decision must be `AUTO_APPLY` OR `APPROVED_APPLY`. Any `REQUIRES_APPROVAL` or `BLOCKED` ⇒ refuse the whole apply, write `blocked.json` listing each rejected item's reason and (where applicable) the missing-binding details so the operator knows exactly what token/permit to mint. No partial application.

This resolves the heartbeat/apply tension: heartbeat is purely informational; autonomous apply is one explicit flag that is itself a `permission_change`-class declaration (changing it via update requires approval). It also resolves the approval/autoapply tension: risky migrations CAN flow through autoapply, but only when an exact-match approval has been pre-staged on the install — without one, the autoapply run is a no-op + a blocked.json report.

## Phases

### P1 — Local update apply with rollback (week 1–2, 2 weeks)

- Manifest types, lockfile reader/writer with pinned-SHA field, plan builder with per-path pre-state and the full risky-change taxonomy.
- Policy evaluator (pure, fully unit-tested across all PlanItem types × all policies × approval present/absent/expired/wrong-binding × promotion-to-APPROVED_APPLY when binding matches).
- Apply executor with snapshot+rollback (including absence tombstones), TrustEvidence gate, and the plan-wide accept-set {AUTO_APPLY, APPROVED_APPLY}.
- CLI: `update check`, `update plan`, `update apply`, `update rollback`, `update status`.
- Manifest source: git adapter only; reads tag from lockfile, verifies SHA against lockfile-pinned value. TrustEvidence emitted is `sha_pinned` when matched, `untrusted` otherwise.
- No telemetry. No autoapply job. **Manifest signature verification stubbed (`signed` TrustEvidence not yet possible).**
- **Approval-artifact support in P1 is intentionally limited to `policy_permit` artifacts under the "unsigned-permit mode" of the Approval artifact contract**: P1 installs MUST NOT set `operator_pubkey` in `agentic-os.package.json`, which causes the evaluator to accept unsigned `permits[]` entries in `UPDATE_POLICY.md` whose other bindings (migration_id, manifest_sha, install/customer id, risk_category, expires_at) all match exactly. `signed_token` artifacts are NOT supported in P1: if a token file is present under `registries/approvals/`, the evaluator rejects it as `BLOCKED { reason: "approval_unsigned" }` because no `operator_pubkey` exists to verify against. Token issuance + verification land in P3.
- Doctor extensions: installed version, channel, last check/apply, rollback availability, pinned manifest SHA, approval inventory with expiries, and a P1-mode banner when `operator_pubkey` is unset (warning operator that unsigned in-policy permits are accepted).

**Exit criteria:** an operator can `update apply` against a local OS root with a manifest whose SHA matches the lockfile pin, see the plan with correct PlanItem types (including a `rule_change` example BLOCKED when no permit is present and APPROVED_APPLY when a matching unsigned `permits[]` entry exists in `UPDATE_POLICY.md` — signed tokens are out of scope until P3), see rollback artifacts including absence tombstones for additive files, and undo with `update rollback --run <id>` while preserving an operator-edited path (verified by byte-level diff). A negative test asserts that a `registries/approvals/<id>.token` file placed on a P1 install is rejected with `BLOCKED { reason: "approval_unsigned" }` even when every other binding matches.

### P2 — Phone home and fleet visibility (week 3–4, 2 weeks)

- Redactor + Heartbeat schema, schema-validated at both ends.
- HTTPS telemetry adapter; `update heartbeat` CLI; scheduled heartbeat job. Heartbeat job NEVER applies.
- Static HTTPS manifest adapter alongside git adapter; channel chooses adapter. Static HTTPS still requires a signed manifest in P3 to be trusted.
- Operator dashboard: read-only CLI `agentic-os fleet status` over collected heartbeats.
- Rate limiting: heartbeat client backs off on 429/5xx with jitter; collector caps payload to 4KB and rejects above.
- Telemetry default-OFF gate enforced: init wires the noop adapter unless both `telemetry_enabled: true` and `heartbeat_url` are present.
- Approval artifacts: still policy_permit only; P2 does not introduce signed tokens or operator_pubkey.

**Exit criteria:** ten test installs explicitly configured with `telemetry_enabled: true` report into a collector; operator sees install_id, version, channel, capability_hash, doctor summary. A paired test confirms ten installs WITHOUT the flag make zero network requests (verified by a network-blocking test harness). Collector-side schema strict check + redactor fuzz test in CI pass.

### P3 — Customer fleet auto-apply with signed approval workflow (week 5–6, 2 weeks)

- **Signed approval tokens ship.** Operator CLI `agentic-os approve` issues ed25519-signed tokens under `registries/approvals/<migration_id>.token`; install CLI verifies against `operator_pubkey` from `agentic-os.package.json` and stores them. Bindings unchanged from the contract (migration_id, manifest_sha, install_or_customer_id, risk_category, expires_at ≤ 90 days). Operator key generation/distribution doc lands with this phase.
- **`operator_pubkey` is set on every customer install moving to P3** as part of the upgrade migration. Setting `operator_pubkey` is itself a `permission_change` PlanItem and ships as an approved migration with a generated install-bound `policy_permit` so each install can authorize its own upgrade out of P1's unsigned-permit mode. After the upgrade, both `signed_token` and `policy_permit` artifacts require valid signatures.
- **Manifest signing REQUIRED for stable-channel auto-apply.** Manifests without a valid signature against `operator_pubkey` yield TrustEvidence `untrusted` ⇒ all PlanItems BLOCKED. The lockfile-pinned-SHA path remains as an alternative trust anchor ONLY for installs that explicitly elect `trust_mode: sha_pinned` in their package manifest.
- `UPDATE_POLICY.md` machine-parseable frontmatter (`permits:`, `autonomous_apply:`, `telemetry_enabled:`, `heartbeat_url:`); doctor parses on every run, any unparseable line is a blocker.
- Per-customer policy bundling: customer install declares `customer_id`; operator dashboard groups by customer_id.
- Migration runner: migrations are named scripts in the package, executed only when their evaluator decision is `APPROVED_APPLY`; each writes a marker into `06-runs-and-logs/updates/<ts>/migrations/<id>.json` that includes the consumed `approval_ref`.
- `update.autoapply.job.ts` scheduled only on installs with `autonomous_apply: true`. Accepts both `AUTO_APPLY` (safe additive) and `APPROVED_APPLY` (approved risky) items; refuses any plan containing `REQUIRES_APPROVAL` or `BLOCKED` items.

**Exit criteria:** operator signs ten install-bound `signed_token` approval tokens (one per install) for a single migration on a signed manifest; ten stable-channel customer installs with `autonomous_apply: true` and `operator_pubkey` set apply the migration via their autoapply job within 1 hour (decision recorded as `APPROVED_APPLY` for each, with `approval_ref` pointing at the install-specific token); three of them roll back successfully via the rollback CLI; the dashboard reflects all of it. Negative test A: an eleventh install WITHOUT a matching token sees the same plan, the autoapply job writes `blocked.json` naming the missing binding, and the migration marker is NOT written. Negative test B: a second manifest with the same migration id but a different SHA is BLOCKED on all ten installs because each token's `manifest_sha` no longer matches; the executor records `BLOCKED { reason: "approval_for_different_manifest" }` and applies nothing. Negative test C: an install with `operator_pubkey` set but a `policy_permit` lacking a signature is BLOCKED with `approval_unsigned` (confirming the P1→P3 mode transition is one-way).

## Acceptance Criteria

1. `update apply` on a root without `.agentic_root` exits non-zero with code 2 and writes nothing. (Test: integration.)
2. `update apply` never overwrites `agentic-os.local.json` regardless of manifest contents. (Test: unit + integration.)
3. Every PlanItem applied by the executor has a corresponding `PolicyDecision ∈ {AUTO_APPLY, APPROVED_APPLY}` recorded in `06-runs-and-logs/updates/<ts>/decisions.json`. APPROVED_APPLY entries include the `approval_ref` pointing at the consumed approval artifact. (Test: integration asserts 1:1.)
4. A PlanItem with `type ∈ {exec_change, hook_change, mcp_change, permission_change, rule_change, instruction_change, skill_change, schema_change, behavior_registry_change, migration}` on a customer install is `REQUIRES_APPROVAL` when no artifact is present, `BLOCKED` when an artifact is present but any of (migration_id, manifest_sha, install/customer id, risk_category, expires_at, signature-where-required) fails to match exactly, and `APPROVED_APPLY` only when ALL bindings match and the artifact is unexpired and (where required by the artifact-kind/operator_pubkey rules) validly signed. The executor applies the item only in the APPROVED_APPLY case. (Test: unit on evaluator covering each transition, integration on executor.)
5. Heartbeat payload sent to the telemetry adapter conforms to `HeartbeatPayload` schema (`.strict()`); extra keys cause the adapter to throw before sending. (Test: unit with fuzzed input.)
6. Heartbeat payload contains no value from `process.env`, no file contents from outside the install root, and no `customer_id` unless `UPDATE_POLICY.md` opts in. (Test: property test that mutates env and FS, asserts payload unchanged.)
7. `update rollback --run <id>` restores every file recorded as `{exists: true}` to its pre-apply SHA, and deletes every file recorded as `{exists: false}` ONLY when its current SHA matches the post-apply SHA recorded for that PlanItem; modified files are preserved and reported as `preserved_local_edit`. (Test: integration including an operator edit between apply and rollback.)
8. Concurrent `update apply` invocations against the same root: second exits non-zero with code 11 and changes nothing. (Test: integration with two processes.)
9. `agentic-os doctor` reports installed version, channel, last check, last apply, pending updates, last successful update, failed update attempts, rollback availability, phone-home status, telemetry policy status, pinned manifest SHA, approval inventory with expiries, and operator_pubkey presence (P1-mode banner when unset). Missing any field is a doctor blocker. (Test: snapshot.)
10. A manifest with `minimum_supported_version > installed_version` causes `update plan` to refuse with a clear error naming both versions. (Test: unit.)
11. A manifest with `TrustEvidence == untrusted` on a non-`dev` channel causes `update apply` to exit with code 12, writing no files; `update plan` still produces a plan but tags every PlanItem `BLOCKED { reason: "manifest_untrusted" }`. (Test: integration.)
12. `update.heartbeat.job` runs on its cadence without invoking the apply executor. `update.autoapply.job` is only scheduled on installs with `autonomous_apply: true`. On a scheduled run, the autoapply job applies a plan iff EVERY PlanItem's decision ∈ {AUTO_APPLY, APPROVED_APPLY}; the presence of any `REQUIRES_APPROVAL` or `BLOCKED` item causes the whole plan to be refused with a `blocked.json` artifact listing each rejected item's reason, and zero files are modified. (Test: integration over a 30-second simulated cron tick on three configurations: no flag → no autoapply job scheduled; flag + plan of only AUTO_APPLY items → applies; flag + plan mixing AUTO_APPLY and APPROVED_APPLY items with matching approvals → applies all; flag + plan with one REQUIRES_APPROVAL item → refuses the whole plan, writes blocked.json.)
13. With `telemetry_enabled` absent or false in `UPDATE_POLICY.md`, init wires the noop adapter; an attempted `send()` makes zero network calls (verified by a network-blocking test harness). (Test: integration.)
14. An approval artifact with mismatched `manifest_sha`, expired `expires_at`, wrong `install_id`/`customer_id`, or wrong `risk_category` produces a `BLOCKED` decision (never `REQUIRES_APPROVAL`, never `APPROVED_APPLY`). A correctly-matching artifact produces `APPROVED_APPLY` and the executor applies the item. (Test: unit covering each mismatch and the matching case.)
15. A new path added to the package manifest with no glob classification rule causes CI to fail with an `unknown PlanItem type` error. (Test: CI lint.)
16. The autoapply job re-runs the evaluator at write time against the on-disk approval set, not just the plan-time decision. If an approval is revoked (file deleted) between plan and apply, the previously-APPROVED_APPLY item becomes REQUIRES_APPROVAL and the whole apply is refused. (Test: integration that deletes the artifact between plan and apply.)
17. Signature enforcement is governed by artifact kind and `operator_pubkey` presence: (a) `signed_token` ALWAYS requires a valid ed25519 signature against `operator_pubkey`; if `operator_pubkey` is unset, `signed_token` is BLOCKED with `approval_unsigned`. (b) `policy_permit` requires a valid signature iff `operator_pubkey` is set; with `operator_pubkey` unset (P1 mode), unsigned `policy_permit` entries are accepted; with `operator_pubkey` set, unsigned `policy_permit` entries are BLOCKED with `approval_unsigned`. (Test: unit covering all four combinations of {signed_token, policy_permit} × {operator_pubkey set, unset}.)

## Validations

- **Unit:** policy.evaluator (all PlanItem types × all policies × approval present/absent/expired/wrong-sha/wrong-category/wrong-target × the promotion path REQUIRES_APPROVAL→APPROVED_APPLY when binding matches × signature enforcement matrix from AC #17, and the BLOCKED-not-degraded behavior when binding fails), redactor (schema + fuzz), plan.builder (drift detection: file edited locally vs manifest expects original; path classification via globs+sniffing; unknown ⇒ strictest fallback), rollback.snapshot (round-trip with `{exists: false}` tombstones and operator-edit preservation).
- **Integration (per phase):** P1 — full apply+rollback against a fixture root including tombstone rollback, operator-edit preservation, untrusted-manifest refusal, a matching unsigned `policy_permit` APPROVED_APPLY happy path on a rule_change item (with `operator_pubkey` unset), AND a negative test that a `signed_token` artifact is BLOCKED on a P1 install. P2 — heartbeat round-trip against an in-process collector with strict schema, plus default-OFF assertion. P3 — multi-install fleet sim (10 installs in tmpdirs with `operator_pubkey` set, ten install-bound signed_tokens, assert apply on all ten producing APPROVED_APPLY decisions; assert an eleventh install without a token is refused at the autoapply gate; assert a second manifest with different SHA blocks all ten; assert expired tokens block; assert revocation between plan and apply blocks; assert an unsigned policy_permit on an `operator_pubkey`-set install is BLOCKED).
- **CI gate:** redactor fuzz test on every PR. A new field added to the heartbeat schema requires a paired test asserting it is constructed from a named source, not copied from a map. A new PlanItem type requires a paired evaluator test asserting (a) the default decision on customer roots when no approval is present and (b) the promotion path when a matching approval IS present. Path classification lint asserts no path resolves to `unknown`.
- **Manual:** before each release, operator runs `update apply` on their own dogfood root and confirms rollback works.

## Risks

1. **Drift between manifest schema and installed lockfile schema.** Mitigation: `schema_version` field on both; lockfile migration is itself a `schema_change` PlanItem with its own approval path.
2. **Apply mid-flight crash leaves install in mixed state.** Mitigation: lock-last commit; rollback snapshot (with absence tombstones) precedes every write; `update status` detects in-progress runs and prompts `rollback`.
3. **Operator's signing key compromise (P3+).** Mitigation: tokens carry `expires_at` (max 90 days in v1); operator publishes a revocation list at a well-known URL; installs check it on every plan. (Opt-in in v1, mandatory in v1.1.)
4. **Customer disables phone-home and falls behind on security updates.** Mitigation: `customer_id`-grouped dashboard surfaces "last heartbeat > 30d ago" as a yellow signal. Documented quarterly out-of-band check-in process.
5. **Telemetry endpoint leaks payloads on its own (logs, indexing).** Mitigation: collector is open-source and minimal; documented guidance to disable request body logging; payload already redacted by source.
6. **`UPDATE_POLICY.md` drifts from actual frontmatter parsing.** Mitigation: doctor parses on every run and reports any unparseable line as a blocker; frontmatter validated against a fixed Zod schema.
7. **Operator forgets a PlanItem category when adding a new file pattern.** Mitigation: plan builder requires every path-glob to map to a known PlanItem type; unrecognized paths default to the strictest applicable category; CI lints for `unknown`.
8. **Approval artifact replayed against a future manifest with the same migration id.** Mitigation: `manifest_sha` binding makes the artifact usable only against one manifest; reissuing for a new SHA is one CLI command.
9. **P1 unsigned-permit mode misused on a customer install.** Mitigation: customer installs in P1 surface the P1-mode banner in doctor; operator-visible dashboard marks any install lacking `operator_pubkey` as "unsigned-permit mode"; P1 installs cannot be reached by the autoapply job (autoapply ships in P3 and requires the P1→P3 upgrade migration, which sets `operator_pubkey`). The risk window is bounded to the manual-apply phase.
10. **Mass-approve mistake: operator issues a wildcard token by accident.** Mitigation: wildcard `install_id: "*"` tokens forbidden on customer roots (evaluator rejects with `BLOCKED { reason: "approval_wildcard_forbidden" }`); operator CLI requires `--confirm-wildcard` flag and writes a Decisions log entry.

## What's NOT in v1

- Hosted update service. (P3 uses static HTTPS + git; hosted comes post-v1.)
- Notion-backed control plane. (Notion can mirror dashboard state but is never source of truth.)
- Cross-install migration coordination (e.g., "apply this only after install X reports ok"). Out of scope; would require central state.
- Binary diffing / delta updates. (Full-file replace with checksum verify.)
- Revocation list enforcement (opt-in in v1, mandatory v1.1).
- UI dashboard. (CLI `fleet status` in v1; web UI later.)
- Multi-tenant operator support (one operator identity per fleet in v1).
- Telemetry default-ON on any channel. (All channels default OFF; operator/customer must declare both flags in UPDATE_POLICY.md.)
- Heartbeat-driven apply. (Heartbeat is informational only; apply requires either CLI or the explicit, opt-in autoapply job, and even that job refuses any plan containing a non-{AUTO_APPLY, APPROVED_APPLY} item.)
- Approval artifacts without expiry. (All artifacts must have `expires_at` ≤ 90 days from issuance in v1.)
- Wildcard `install_id: "*"` artifacts on customer roots. (Allowed only on operator roots in v1.)
- A fifth PolicyDecision variant. (The union is closed at AUTO_APPLY, APPROVED_APPLY, REQUIRES_APPROVAL, BLOCKED; adding a variant requires a spec amendment and an evaluator test sweep.)
- Signed approval tokens in P1 or P2. (Token issuance and verification ship in P3 alongside `operator_pubkey` distribution; P1/P2 use unsigned `policy_permit` artifacts under the unsigned-permit mode of the Approval artifact contract.)
- A mode that mixes signed tokens with unsigned in-policy permits. (Once `operator_pubkey` is set on an install, ALL artifact kinds require valid signatures; there is no per-artifact opt-out.)
