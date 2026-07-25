# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) computed from Conventional Commits
(breaking → major, `feat` → minor, `fix`/`perf` → patch).

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
