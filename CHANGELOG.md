# Changelog

## Unreleased

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) computed from Conventional Commits
(breaking → major, `feat` → minor, `fix`/`perf` → patch).

## [Unreleased]

### Fixed

- Derive same-head Team PR completion-effect identity from the retry-aware
  review intent even when the optional review-mode field is omitted, and carry
  the admitted Slack channel/thread binding through projection.

## [0.8.1] - 2026-08-17

### Fixed

- Admit the Team PR producer's validated retry nonce, propagate it to the
  installed helper, and retain it in the completion effect so explicit
  same-head rechecks cannot reuse an earlier worker intent or receipt.
- Complete the v0.8.0 Python, Node, static manifest, chart, and lockfile version
  projections so locked CI and the next immutable patch release validate from
  one coherent version.

## [0.8.0] - 2026-08-17

### Added

- Add the governed production-release validation workflow and durable run-log
  storage support.

### Fixed

- Recover legacy Auto-Dev delivery boundaries, preserve RunLogStore state, and
  restart loaded macOS execution-fabric services after release activation.
- Align Commitizen's package, hook, lockfile, and enforcement contract at
  version 4.17.1.

## [0.7.1] - 2026-08-15

### Added

- Add report-only Compose pressure teardown proposals backed by typed lifecycle,
  provider, worktree, dirty-state, and runtime ownership evidence, plus a
  separately invoked exact-fingerprint executor that retains named volumes.

### Changed

- Make root validation bounded and observable with hard wall-clock,
  no-progress, cancellation, and scoped fallback behavior.
- Allow Health to remove an external worktree only through its exact
  project-owned registration while preserving the existing merge, review,
  branch, cleanliness, and runtime cleanup gates.

### Fixed

- Preserve the active PR-Create escalation as the authoritative Develop
  predecessor throughout the governed Review-to-Merge chain.
- Preserve partial portfolio state when an exhausted executor handoff coexists
  with a recoverable handoff.
- Bind opposing-review receipt run IDs to their deterministic artifact
  directory leaves and ingest structured blocking and advisory findings
  without allowing blocking evidence to be verified away.
- Require same-head advisory recovery to match explicit non-blocking evidence
  and remain bound to the immutable reviewer response and canonical findings
  digest; honor routed `continue_with_receipt` handling when an unavailable
  review is policy-allowed.
- Validate required PR checks only after exact-head workflow contexts have had
  two settled observations to appear, rejecting stale labels without failing
  during the downstream-check emission gap.

## [0.7.0] - 2026-08-14

### Added

- Add a shared, exact-head review coordinator with stable identities,
  single-flight claims, normalized findings ledgers, immutable receipts, and
  evidence-gated operator resolution after the review circuit is exhausted.
- Add a transactional local release-runtime installer with hash-pinned
  dependency closure, rollout quiescence proof, receipt-ledger migration, and
  verified rollback pointers.

### Changed

- Make Review Self the sole owner of the initial full review. Repair uses at
  most three descendant delta reviews, Finalize reuses the exact-head receipt,
  and provider publication is deferred to one clean terminal summary.
- Require exact-head review authority, local tests, hosted checks, and policy
  identity before Auto-Dev can enter `ready_for_merge`.

### Fixed

- Prevent replayed, concurrent, aliased, corrupt, or cross-entrypoint review
  requests from recreating the duplicate-review storm observed on PR #19.
- Preserve review budgets across scrub failures, quarantine, legacy receipt
  migration, and release rollout.

## [0.6.3] - 2026-08-13

### Fixed

- Export the canonical Team PR review outcome after validating the helper's
  successful lifecycle status, so `succeeded + findings` reaches the Fabric
  projector as a completed review rather than a failed task.

## [0.6.2] - 2026-08-13

### Fixed

- Strictly validate current and legacy Team PR Fabric receipt wrapper shapes,
  so a completed review with findings reaches projection while malformed
  wrappers cannot be accepted.
- Run the BigMac Execution Fabric alarm dispatcher through its immutable worker
  Python runtime, so governed notification delivery does not silently fail when
  launchd resolves a system interpreter without PyYAML.

## [0.6.1] - 2026-08-13

### Fixed
- Recover legacy PR-create and worktree-ready delivery packets through the
  governed Auto-Dev workflow.
- Preserve queue isolation, canonical source-branch refresh, policy routing,
  and exact legacy PR identity during delivery validation.
- Make policy migration and admission contention handling fail closed and
  idempotent.
- Persist full-identity Team PR review intent before helper launch, recover a
  completed helper receipt after worker interruption, fence overlapping
  attempts per review identity, and bind the helper to the exact review mode,
  run ID, and summary path. Full-digest receipt paths, fsync-backed
  persistence, and a durable helper-launch marker prevent cross-ticket recovery
  collisions, torn intent writes, and relaunch while the PID still belongs to
  the exact helper run. A shared marker lock prevents dispatch-failure writes
  from clobbering a concurrently registered helper PID. Fresh and recovered
  successes terminalize the marker.
- Normalize case-insensitive repository, head, and source-key fields before
  deriving the cross-repository review identity and helper run ID.
- Keep the legacy projection key for already-admitted tasks that omitted
  `review_mode`, while explicit current tasks use the full-intent key; this
  preserves effect dedup across the upgrade boundary.
- Persist the first effect-key format per immutable review identity so legacy
  and current task shapes cannot project the same helper result under two keys;
  classify PID-less governor exceptions as retryable dispatch failures.
- Keep enough bounded review attempts for error-driven retries to outlive the
  helper fence, and classify transient durable-write, lock, and host-identity
  failures as retryable.
- Validate each recorded effect key against its declared format, durably
  materialize a valid stdout fallback summary, and remove host-ineligible
  pinned queues before worker registration and claim.
- Pin the host-local Team PR durability state to `bigmac`; a worker on any
  other host fails retryably before helper execution.
- Derive the helper receipt domain from the validated task route so the generic
  execution-fabric package does not hard-code a private domain path.
- Classify a failed helper with a dead registered PID instead of consuming the
  retry budget as perpetually in progress, while keeping a live but
  unverifiable PID fail-closed behind the orphan fence.
- Preserve invalid-receipt classification and receipt paths for byte-corrupt
  JSON, and classify a dispatch exception with a dead registered helper PID
  immediately instead of spending an extra retry as in progress.
- Ship the Agentic OS route before the paired object-library producer; the new
  producer emits explicit `review_mode`, which an older closed route rejects.
  Quiesce the review queue during that 0.5.x-to-0.6.0 upgrade so an
  unacknowledged legacy effect key cannot be replayed once under the full-intent
  key format. The ordering requirement is already satisfied for 0.6.0-to-0.6.1.

## [0.6.0] - 2026-08-01

### Added
- Consolidate GitHub, Jira, Linear, and Notion access through provider bridges
  with bounded reads and explicit mutation boundaries.
- Add a canonical, receipt-backed opposing-model Auto-Dev review command shared
  by Claude and Codex harnesses.
- Add guarded Docker and OrbStack reclaim reporting for orphaned worktree
  resources without expanding Auto-Dev cleanup authority.

### Fixed
- Support legacy execution-fabric role-health bootstrap during protected
  rollout reconciliation.

## [0.5.7] - 2026-07-29

### Added
- Install one reusable, additive-only release contract with immutable tag/SHA
  verification and complete release-asset identity readback.
- Publish one canonical release policy for Agentic OS and the adopting Harness,
  Library, and Brain repository roles.

### Fixed
- Require execution-fabric repair roles to prove active promoted-role health and
  preserve convergence, recovery, and failure visibility before reporting a
  healthy state.
- Reject prerelease and build-metadata versions in the current Agentic OS
  adapter before artifact builds, avoiding late Python filename-normalization
  mismatches.

## [0.5.6] - 2026-07-26

### Changed
- Recover and register generated harness skill adapters.
- Consolidate Auto-Dev PR delivery, GitFlow topology, review, and quality-gate workflows.

## [0.5.5] - 2026-07-26

### Fixed
- Invoke the canonical Agentic OS notifier with the configured released Python
  runtime when one is available. macOS launchd otherwise resolves the notifier's
  env-based shebang to Apple's bare Python, which lacks required packages and
  could drop a critical fallback alert before it reached durable history.
- Exercise the personal-fallback alert through the configured worker Python so
  deployment tests cover the same dependency boundary used on bigmac.

## [0.5.4] - 2026-07-26

### Fixed
- Preserve the valid JSON boolean `false` when the personal-fallback watchdog
  reads primary readiness. The previous `jq -e` invocation activated the local
  fallback state but exited before emitting the required critical alert.
- Add an executable watchdog regression proving that a standby-to-active
  transition with `primary_ready=false` returns successfully and invokes the
  Agentic OS notifier at critical severity.

## [0.5.3] - 2026-07-26

### Fixed
- Translate canonical route approval classes into the run queue's distinct
  approval-state vocabulary. Policy-gated remote work records `approved`, and
  an explicitly applied local fallback submission records `approved`, instead
  of persisting invalid `policy_gated` or `explicit` enum values.
- Exercise explicit local fallback admission against the SQLite execution
  fabric so the genomesbox-offline path is release-gated by the same state
  contract used on bigmac.

## [0.5.2] - 2026-07-26

### Fixed
- Generate the MinIO observer policy using POSIX shell built-ins. The pinned
  MinIO client image does not ship `sed`, so v0.5.1 could create the bucket and
  observer user but could not complete a fresh primary bootstrap.
- Add a deployment-contract regression that rejects the unavailable external
  command and unresolved bucket placeholder.
- Preserve the control-plane image command when Compose overrides its
  datastore-secret entrypoint; without the explicit command the container
  exited successfully before opening the API or applying its schema.
- Validate every artifact/API credential that the control plane requires at
  preflight and override image-default health checks for loop and gateway roles
  so healthy workers are not reported against the control-plane port.

## [0.5.1] - 2026-07-26

### Fixed
- Build and prune the leadership-witness production dependency tree on the
  native BuildKit platform, avoiding QEMU execution during multi-architecture
  release assembly.
- Preserve the v0.5.0 tag as the receipt for the failed unpublished release;
  v0.5.1 is the first installable personal-primary release.

## [0.5.0] - 2026-07-25

### Added
- Personal `remote_with_local_fallback` transport for genomesbox-primary
  installations. A durable bigmac latch activates its existing local queue
  only after sustained primary readiness failures, alerts through Agentic OS,
  and requires explicit readiness-gated failback.
- Explicit non-HA `standalone_primary` authority for genomesbox, backed by a
  co-located short-lived signed witness, exact-host canonical policy opt-in,
  local PostgreSQL durability proof, normal scheduler/effect/task operation,
  and disabled shared-ledger promotion and failback.
- Runner-bounded one-shot standalone witness bootstrap, readiness-before-primary
  ordering, governed local policy rotation, and personal-mode suppression of
  the HA-only artifact-replication timer.

### Fixed
- Installed Compose releases now mount canonical queue policy and managed schema
  from `FABRIC_OS_ROOT` instead of invalid source-tree-relative paths.
- Emergency bundles now consume the released seven-image JSON lock through one
  strict env materializer and reject missing witness/worker pins or drift
  between canonical and runtime lock forms.

## [0.4.2] - 2026-07-25

### Added
- A provider-neutral leadership witness that runs as a digest-pinned OCI image
  on an independent third host, stores authority in durable SQLite, binds to an
  operator-selected private address, and emits health receipts and Agentic OS
  alerts through a supervised monitor.
- End-to-end witness durability checks covering explicit first bootstrap,
  restart recovery, missing or corrupt state, concurrent promotion attempts,
  response-loss replay, immutable container configuration, and protected
  state and secret mounts.

### Fixed
- Witness promotion now commits the authority transition, audit record, and
  signed receipt in one durable transaction before local database promotion;
  retries recover the original receipt instead of guessing new state.
- Runtime installation is separate from explicit activation, repeated
  activation is idempotent, paths containing spaces remain intact, PostgreSQL
  replication slots follow their target host, datastore credentials stay in
  protected files, and backup health requires a disposable restore.
- Release validation now covers Python metadata and lock state, both Node
  services and their npm lock roots, the worker Helm chart, and the static
  release manifest. Tagged releases must be reachable from `main`, cannot
  replace existing release assets, and run the real witness OCI smoke in CI.

### Changed
- The independent witness has no cloud-provider deployment dependency. When a
  third host is unavailable, `manual_fail_closed` starts no witness and keeps
  automatic promotion and failover disabled.
- Cross-host run artifacts continue to use the S3-compatible object protocol,
  including MinIO deployments, without coupling leadership authority to the
  artifact store.

### Dependencies
- Updated `pnpm/action-setup` from v4 to v6 in CI (#92).

## [0.4.1] - 2026-07-25

### Fixed
- Preserved strict `not_required` Auto-Dev stage receipts when the surrounding
  work item already has a reviewed subject revision.
- Generated `SHA256SUMS` from published assets only by keeping checksum staging
  outside the release asset directory.

### Changed
- Advanced the Python package, runtime module, Node services, Helm chart, and
  release manifest together under one canonical version.

## [0.4.0] - 2026-07-24

### Added
- Unified named-queue Execution Fabric with PostgreSQL truth, BullMQ/Valkey
  delivery, bounded workers, durable effects, health findings, alarms,
  deterministic healing, and fenced genomesbox/bigmac leadership.
- Portable task-attempt run artifacts through a MinIO/S3-compatible contract,
  exact signed PUT headers, stored-object SHA-256 verification, durable
  workload-bound spool recovery, central spool health, terminal quarantine,
  bidirectional replication receipts, and promotion/failback artifact-RPO
  gates.
- Command Center queue, worker, run, effect, alarm, healing, configuration,
  and failover visibility plus canonical runtime configuration commands.
- Digest-pinned control-plane and witness images, release manifest, image lock,
  checksums, SBOM, emergency bundle, Compose/systemd/launchd/Helm assets, and a
  single-writer GitHub release workflow.
- A generic single-identity Kubernetes worker chart with mandatory RWX state,
  closed route validation, and explicit separation from LOSMON domain handlers.

### Changed
- Package, control-plane service, witness service, and Helm app versions now
  advance together under one validated release manifest.
- Direct and source-distribution-derived wheels carry the same cache-free
  scaffold runtime resources. Large deployment and emergency assets remain in
  the source distribution and GitHub release behind the wheel's asset index.
- GUI development dependencies are locked to patched transitive versions with
  no known audit findings at release validation.

## [0.3.0] - 2026-07-24

### Added
- Policy-composed Auto-Doctor host health reporting, repair planning,
  provider-neutral report projections, and fail-closed workspace validation
  (#71).

### Fixed
- Auto-Dev lifecycle gates, inherited PR-stage knowledge, and quiet PR
  delivery checks (#87, #90, #91).
- Long-running status waits now use bounded backoff with a final state reread
  to avoid timing-related test failures (#86).

### Changed
- Consolidated Auto-Dev and version-object library installs (#74).

### Dependencies
- actions/setup-node v6 → v7 (#89); @vitejs/plugin-react v5 → v6 (#60).

## [0.2.0] - 2026-07-22

### Added
- Command Center foundation: design tokens, resizable shell, split/page
  registry, and the app architecture docs suite (#78).
- `auto-dev-dep-updater` — governed dependency-update lane: one Renovate PR
  per run, proven against the dependency contract suites, merged under
  written per-repo authority or repaired to green first (#80).
- `auto-dev-continuous-release` — own-PR continuous-delivery loop: review →
  finalize → merge on profile gates, then the SemVer release program and
  post-release documentation run (#82).
- Dependency contract test suites for both surfaces (python
  `tests/contracts/`, GUI `apps/agentic-os-gui/e2e/contracts/`) with
  coverage gates, plus a GUI CI job — every Renovate PR now carries real
  proof (#79).

### Fixed
- react/react-dom updated to 19.2.7 → 19.2.8 as a pair (#72).

### Dependencies
- electron 43.1.1 → 43.2.0 (#75); vite 7.3.6 → 8 (#54);
  actions/setup-python v6 → v7 (#70).

### Policy
- Renovate: one PR at a time, rebase-when-behind, native automerge off (#79);
  react monorepo grouped, typescript majors paused pending a TS7 migration
  work item (#84).

## [0.1.8] - 2026-07-21

Baseline for this changelog; see the `v0.1.8` tag and earlier release PRs.
