# Auto-Dev Validation Contract

- Resolver fixtures prove root/domain/project/invocation order, provider/type
  fallback, stable fingerprints, and monotonic safety.
- Golden drafts cover Jira ADF, rich Notion/Confluence Markdown, Linear, GitHub,
  Slack, and filesystem output.
- Negative fixtures cover malformed frontmatter, missing evidence, secrets,
  local paths, private links, unauthorized apply, target mismatch, stale
  versions, provider/VPN pause/resume, and readback mismatch.
- Artifact fixtures prove required-evidence receipts, semantic-validation
  assertions, typed approval/target verification, normalized provider readback,
  and exact provider-payload hash comparison.
- Development runs snapshot Auto-Dev, environment access, dev standards, QA
  gates, and gitflow topology.
- Start creates exactly one `<work-item>/autodev.json`, links the canonical
  delivery task, and never creates new legacy `artifacts/auto-dev/state.json`.
- Adoption accepts both in-place and registered external-symlink worktrees only
  after link/target, branch/base, configured-repository, and Git metadata
  readback. Default and custom worktree directories are covered. Negative tests
  reject unregistered targets, changed registry links, and branch mismatches
  before state mutation; anonymous rows cannot poison a named registration.
- Every lifecycle mutation refreshes the projection; typed standalone workflow
  receipts are idempotent and never advance Development Delivery by themselves.
- Everything and every single-stage verb parse and preserve the same work item,
  while `not_required` requires a policy reference.
- Everything does not finish before Health is completed, including a receipt-
  audited no-op; Health cannot be `not_required`, and Closeout remains the
  owner of `delivery_complete`.
- Merge accepts only completed typed evidence with `merge_sha`, provider-read
  `source_head_sha` equal to the reviewed `subject_revision`, `provider`,
  `pull_request`, and `readback_verified: true`; Health requires the exact same
  provider, pull-request reference, and merge revision as terminal authority.
- Health refuses to clean before the final receipt audit passes, respects
  reopen/hold markers, limits worktree cleanup to registered known roots, limits
  OrbStack/container teardown to the target-local runtime, and never invokes a
  host-wide/all-resource cleanup.
- LOS fast-worktree Health proves the full declared runtime identity plus exact
  compose-project container/network/volume, database, Redis, Valkey, registry,
  and env-file absence. Negative regressions keep readback blocked when shared
  infra is down, Docker network/volume enumeration fails, or Compose fallback
  leaves project residue, even though the legacy status/grep expression would
  report the slug absent.
- Health writes and reads back a resume manifest, preserves the durable packet,
  moves it to the finished lane, and refreshes task/projection links after the
  move.
- Health relocation uses the real CLI, normalizes legacy `status`/`state`
  metadata, preserves packet-local `WORKLOG.md` and `NEXT.md` hashes, and exits
  successfully with readable output.
- `auto-dev reopen` rejects a manually reactivated `03-complete` packet,
  preserves the finished packet byte-for-byte, creates one fresh active packet,
  worktree, runtime registration, and run, and is idempotent by run id.
- Every shipped Health preflight, runtime-cleanup, resource-cleanup, and
  closed-worktree-readback template and example passes its strict schema. Each
  four-receipt bundle also keeps work-item identities, preflight digest,
  resource identities, terminal revision, and closed-registry linkage aligned.
- No Auto-Dev Health schedule is enabled by installation or validation.
- Every registered workflow has command+skill parity, complete docs, receipts,
  implicit routing, and a manual smoke test.
- Object Library parity includes `agentic-os library`, the `object-library`
  skill, and the `library_self_hosting` workflow plus all three manifests and
  Auto-Dev program dependencies. Its lifecycle proof binds Develop to build,
  QA to the exact archive SHA-256, Release to that same published artifact,
  Deploy to install/doctor readback, and a Document rerun to actual
  post-release truth.
- Library installation tests keep the source repository separate from the
  replaceable installed `lib/` projection, block linked worktrees or
  uncaptured dirt, validate before atomic replacement, preserve rollback and
  install receipts outside `lib/`, and compare installed object count/content
  hash with the source revision receipt.
- Multi-repository profiles require an explicit repository when configured,
  merge per-repository overrides, revalidate the selected profile, and pin the
  selected repository in plan, work-item, worktree, and resume receipts.
- Detective doctors resolve every supported trigger against both investigation
  report and RCA outputs; representative LOS and Kanga routes prove that LOS
  config/rules sources do not leak into Kanga.
- Detective rejects undeclared sources, wrong authority classes, unsatisfied
  prerequisites, unverified version/availability receipts, pending source
  coverage, uncited facts/hypotheses/conclusions, and high confidence with an
  unavailable planned source.
- Every Development Delivery workflow embeds the shipped SVG flowchart, and a
  clean installed root exposes the library-backed Auto-Dev program through its
  compatibility symlink and refreshed library registry.
- Source strict validation, library doctor, installed OS validation, and Notion
  hierarchy/readback must pass before release.
