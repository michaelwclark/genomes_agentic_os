# Auto-Dev Worklog

## 2026-07-29 — Registered external worktree adoption

- Removed the contradictory project-boundary rejection for valid external
  worktrees registered through the supported project-visible symlink policy.
- Adoption now resolves relative canonical paths from the installed OS root and
  verifies every active registry copy, the visible link and resolved target,
  branch and base branch, configured repository, Git common directory, and
  merge base before writing delivery state.
- Added full CLI adoption coverage for both in-place and external-symlink
  worktrees plus negative regressions for unregistered targets, changed links,
  and branch mismatches.

## 2026-07-21 — Object Library self-hosting

- Defined one plain-English source/install topology: reusable definitions are
  authored in `michaelwclark/genomes_agentic_lib`; installed `lib/` is a
  validated replaceable projection with runtime-owned receipts and backups.
- Added command, skill, workflow, manifest, program-component, dependency, and
  parity contracts for Object Library work without adding a new state machine.
- Reused Auto-Dev Develop for build, QA for exact-artifact validation, Release
  for publication, Deploy for installation/readback, and a Document rerun for
  post-release truth.
- Consolidated all five development policy planes under `auto_dev/` and kept
  artifact/investigation contracts adjacent rather than counting them as extra
  development planes.

## 2026-07-20 — LOS runtime proof hardening

- Added a source-owned LOS fast-worktree Health wrapper that binds the frozen
  domain/project/worktree identity to the exact Git worktree, runtime registry
  row, compose containers/networks/volumes, database, cache prefixes, and env
  file while excluding the shared external LOS network.
- Replaced the unsafe sample `status.sh | grep` readback with explicit
  Postgres, Redis, and Valkey queries. Shared infra down/unqueryable now blocks
  both teardown and readback instead of hiding residual DB/cache state.
- Added a copyable LOS project runtime overlay, provider examples, component
  registration, and focused negative tests for infra-down, Docker enumeration
  failure, failed-Compose network residue, and DB/cache residue.

## 2026-07-20 — Health lifecycle workflow

- Added Health as the final Auto-Dev stage after Closeout. Closeout continues to
  reconcile provider/delivery state and prove `delivery_complete`; Health owns
  the final receipt audit and lifecycle hygiene.
- Defined receipt-first, dry-run-first cleanup for one exact registered
  reconstructable worktree and one identity-bound target-local runtime. Cleanup
  has no force, metadata-sweep, host-wide/all-resource, shared-runtime, or guessed-
  identity path; reopen/hold markers stop cleanup.
- Kept the durable work-item packet and compact receipts, added a resume
  manifest, and moved completed packets to the canonical finished lane instead
  of deleting history.
- Added a full pre-cleanup packet manifest, exact worktree id/path/branch/HEAD
  checks, domain/project/worktree runtime identities, packet-local teardown and
  readback hashes, a 15-minute freshness window, and an immediate readback whose
  exit 0 means the exact registered worktree runtime is absent. Only `work.yml`
  and `autodev.json` may change semantically during the finished-lane move.
- Required ten final Health receipt kinds: terminal authority, Closeout, receipt
  audit, resume manifest, packet manifest, resource cleanup, runtime cleanup,
  work state, active index, and validation.
- Kept Health manually runnable with command/skill parity. No schedule or
  automation was enabled.

## 2026-07-20 — Everything, single-stage verbs, and work-item state

- Added the `agentic-os auto-dev` plain-English facade, `/auto-dev-everything`,
  and the exact ordered family: Groom, Detective, Create Artifacts, Readiness,
  Develop, Document, PR Create, Review Self, Review Others, QA, Finalize, Merge,
  Release, Deploy, Closeout, and Health. Every workflow keeps an independently
  callable command and skill. The lower-level `release_propagation` recorder and
  legacy command remain compatibility surfaces for PR Create, not another stage.
- Added `<work-item>/autodev.json` as an atomic cross-workflow projection over
  Development Delivery, typed standalone workflow receipts, sync/readback, and
  legacy read-only references.
- Defined multi-ticket runs as one task/packet/`autodev.json` per ticket with
  ticket-local resume, and finished packets as immutable history that require a
  receipt-backed canonical reopen plus a fresh delivery run.
- Bound `not_required` to a typed identity/policy/fingerprint/hash decision and
  bound Merge to immutable Finalize-versus-Review-Others authorship authority,
  configured repository/base, provider-read identity, and exact revision chain.
- Added `auto_dev` and `environment_access` Markdown planes with root stage
  policy and sparse domain/project additions for every registered project.
- Kept manual kickoff canonical. No schedule or opened-PR automation was
  enabled; future adapters must invoke the same entrypoint and state contract.

## 2026-07-20 — overlap inventory and retirement controls

- Replaced the category-only Archive Soon notes with a stable, item-by-item
  migration ledger spanning delivery state, review/PR helpers, LOS/Kanga
  evidence transports, Jira/Linear intake, reports, provider adapters, installed
  program copies, routing, and policy-path compatibility.
- Each surface now has an owner, overlap statement, canonical replacement,
  migration action, parity verification, retirement gate, and explicit status.
- Protected unique source, provider, review, queue, and lifecycle capabilities as
  retained adapters instead of treating every overlap as deletable duplication.
- No capability was retired by this documentation pass. Install parity,
  migration receipts, observation windows, and the recorded operator decisions
  remain required before archive actions.

## 2026-07-19 — vNext foundation

- Established Auto-Dev as the operator-facing SDLC family while retaining
  Development Delivery as the durable execution engine.
- Added dynamic development, QA, gitflow, and artifact Markdown policy planes.
- Added provider/type artifact resolution, rendering, validation, governed
  apply, external adapter handoff, readback, receipts, CLI, command, skill, and
  workflow documentation.
- Added the overlap/retirement ledger in `ARCHIVE_SOON.md`.
- Added Detective policy resolution, deployed-version gating, source manifests,
  evidence/event ledgers, VPN/provider pause-resume, hypothesis analysis,
  conclusion and artifact rendering, CLI, command, skill, workflow, and tests.
- Added shared, LOS, Kanga, and Agentic OS policy packs, plus repository-specific
  Django/Vue and five-repository Kanga development/QA/gitflow guidance.
- Published and read back the canonical 22-page Auto-Dev program under Genome's
  Notion → OS Programs, including seven workflow pages, four flowcharts,
  failure/recovery guidance, receipt contracts, and the Archive Soon ledger.
- Corrected live Kanga adapters to the canonical `KANGA-BOOKING` organization,
  all-repository `develop` flow, and `genomes` Linear workspace.
- Completed the closeout slice: the full source suite passed with 1,418 tests;
  a clean wheel built and installed into an isolated root; source, installed,
  and live artifact/Detective doctors passed with zero errors or warnings.
- Installed the wheel into the live development runtime, refreshed the object
  library, registered all seven skills for Agents, Claude, and Codex, and
  activated CLI routing for `develop`, `artifacts`, and `detective`.
- Verified representative LOS, Kanga, and Agentic OS artifact, investigation,
  development, QA, and gitflow resolutions with policy fingerprints and source
  isolation. Added explicit root-inheritance declarations for Personal and
  CashTree and an Agentic OS project policy pack.
- Verified the canonical 22-page Notion projection and four uploaded flowchart
  assets by readback. No overlapping compatibility surface was retired; the 61
  Archive Soon rows remain governed by their individual parity and observation
  gates.
