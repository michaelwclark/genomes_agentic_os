# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) computed from Conventional Commits
(breaking → major, `feat` → minor, `fix`/`perf` → patch).

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
