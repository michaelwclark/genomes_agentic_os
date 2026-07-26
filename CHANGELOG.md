# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) computed from Conventional Commits
(breaking → major, `feat` → minor, `fix`/`perf` → patch).

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
