# Program: Auto-Dev

![Auto-Dev program flow](assets/auto-dev-program.svg)

> **Outcome:** one polymorphic SDLC program whose project profile defines how
> far Default and Everything run—from implementation plus a PR at minimum to a
> complete versioned production release—while preserving typed evidence and a
> resumable work packet.

Operator documentation: [Auto-Dev — Canonical SDLC Program](https://www.notion.so/3a3683b48dab81b88875f5ec875dab3e)
in Genome's Notion. Local definitions and typed receipts remain authoritative.

## How the pieces fit

Auto-Dev is the operator-facing family. `development_delivery` remains its
durable execution engine for work items, worktrees, state transitions, failure
classification, receipts, and delivery state. Create Artifacts owns provider/type
quality. Detective owns evidence-first diagnosis. Domain/project Markdown files
specialize each workflow without forking shared code.

## Workflow map

| Order | Workflow | Use it for | Manual entrypoint | Terminal handoff |
| --- | --- | --- | --- | --- |
| all | Everything | take each ticket through the project's configured workflow boundary | `/auto-dev-everything` | configured completion-stage receipt, or exact blocker |
| 1 | Groom | turn intent into implementation-ready truth | `/auto-dev-grooming` | groom receipt |
| 2 | Detective | bug, QA/log/alert/ticket-comment analysis and RCA | `/auto-dev-detective` | evidence packet, investigation report, or typed policy decision |
| 3 | Create Artifacts | Jira/Linear/Notion/Confluence/GitHub/Slack/filesystem output | `/auto-dev-create-artifacts` | validated/read-back artifact or typed policy decision |
| 4 | Readiness and Context | claim, evidence, repository/base, policy, and plan | `/auto-dev-readiness` | `planned` |
| 5 | Develop | work item/worktree/code/local checks | `/auto-dev-develop` | `local_validation` |
| 6 | Document | code, issue, architecture, operations, QA, release, or handoff docs | `/auto-dev-document` | verified documentation receipt |
| 7 | PR Create | resolve and create or reuse the complete 1-N PR family | `/auto-dev-pr-create`; GitFlow and Release Propagation are aliases | provider-read family receipt |
| 8 | Review Self | opposing review, CI, and repair loops over the exact PR family | `/auto-dev-review-self` | `ready_for_merge` |
| 8a | Opposing Model Review | canonical Claude/Codex review transport and receipt for an exact ticket/head | `/auto-dev-review-self-opposing-model <TICKET>` | `pre_pr_review` or `post_pr_review` receipt |
| 9 | Review Others | review another author's live PR without merging | `/auto-dev-review-others` | clean review-only receipt or typed policy decision |
| 10 | QA | independently callable risk-based validation | `/auto-dev-qa` | QA receipt for the exact reviewed revision |
| 11 | Finalize | converge our PR family and record readiness without merging | `/auto-dev-finalize` | immutable readiness receipt or typed policy decision |
| 12 | Validate Production Release | verify Jira/GitHub family, exact QA, full diff, runtime consumer contracts, and operational release evidence | `/auto-dev-validate-production-release` | immutable pre-merge validation receipt or exact hold |
| 13 | Merge | apply the governed merge decision and read back provider truth | `/auto-dev-merge` | typed `merged` proof or exact hold |
| 14 | Release | publish a version, tag, package, changelog, or provider release | `/auto-dev-release` | release receipt or typed policy decision |
| 15 | Deploy | deploy and validate the exact artifact | `/auto-dev-deploy` | deployed-version proof or typed policy decision |
| 16 | Closeout | reconcile provider and delivery state | `/auto-dev-closeout` | `delivery_complete` |
| 17 | Health | audit receipts, remove exact reconstructable resources, and preserve the finished packet | `/auto-dev-health` | Health receipt and resume manifest |

Release Propagation has no numbered row. Its legacy command delegates to PR
Create, and Development Delivery retains `release_propagation` only as the
lower-level compatibility recorder for the canonical PR Create family receipt.

This is the shared safe order. A project may reorder it only when all required
lifecycle precedence edges remain intact. Any workflow may still be called by
itself, but when it belongs to an Auto-Dev item its active predecessors must
already be terminal and receipt-backed. Stages outside the configured
start/completion boundary are recorded as `out_of_scope`, not invented as
complete.

Each project declares stage applicability as `required`, `contextual`, or
`disabled`. Required stages must complete. Contextual and disabled stages that
fall inside the active workflow need a typed policy decision before they can be
`not_required`. This makes today's skip explicit and lets the project enable the
stage later without changing the shared program.

## Object Library self-hosting profile

Object Library work uses the same stages above; it is not a seventeenth stage
or a second delivery engine. Durable definitions are authored in
`michaelwclark/genomes_agentic_lib`, while `<os-root>/lib/` is the validated,
replaceable installed projection.

| Existing stage | Library responsibility |
| --- | --- |
| Develop | Change source manifests/content and build the deterministic archive plus receipt. |
| QA | Validate the exact candidate archive and bind evidence to its SHA-256. |
| Release | Publish the already verified version, tag, archive, receipt, and changelog. |
| Deploy | Install the immutable released revision, then verify the installed content and run library doctor. |
| Document rerun | After release/deploy, record the actual version, revision, hash, install receipt, and resume path. |

The ordinary PR, review, Finalize, Merge, Closeout, and Health gates remain in
force. The first Document pass stays in its normal pre-PR position; the
post-release update reruns that same workflow and adds linked evidence without
reordering the stage list. Use the `object-library` skill and
`library_self_hosting` workflow for the full source/install contract.

## Polymorphic behavior

The shared engine does not contain LOS, Kanga, Jira, Linear, Django, or Vue
defaults. It composes Markdown at runtime:

```text
root policy -> domain additions -> project additions -> invocation overlay
```

The five development planes share one parent. Use root files directly under
`auto_dev/` for program behavior, then the nested `environment_access/`,
`dev_standards/`, `qa_gates/`, and `gitflow_topology/` folders for their named
concerns. `artifact-config/` and `investigation-config/` are adjacent contracts,
not sixth and seventh development planes. Adding a Markdown file affects the
next run and appears in the fingerprint.

## Invocation model

- **Implicit chat route:** intent phrases in `ROUTER.md` select the workflow.
- **Bare Auto-Dev:** `agentic-os auto-dev default ...` starts the project's
  Default window. The shared default is Readiness through PR Create, and a
  project cannot configure it to stop before PR Create.
- **Everything:** `agentic-os auto-dev everything ...` starts the project's
  Everything window. Everything is project-relative; release and deploy run
  only when they are inside that configured window.
- **Manual:** every workflow exposes a named command/skill and resumes the same
  task state/run packet. `agentic-os auto-dev <verb>` is the CLI grammar.
- **Sub-workflow:** programs pass explicit evidence and receipt references.
- **Trigger adapter:** schedules/queues may start a run but do not own its state.

`<work-item>/autodev.json` is the compact cross-workflow resume file. It points
to Development Delivery's canonical task state and typed receipts; it does not
replace the tracker, provider, SQLite work registry, or delivery state machine.
No Auto-Dev schedule is enabled by this program.

Pre-vNext active packets use the explicit `auto-dev adopt` migration command.
It binds the exact existing packet to its single canonical work row and source
key, creates `autodev.json`, and reuses only an exact registered worktree after
Git and branch readback. A registered external worktree is supported only when
its link on the canonical project `worktrees/` surface, physical target under
the configured directory or another explicitly registered location, branch,
base branch, configured repository, and Git common-directory metadata all
agree. Registry rows without an `id` or `name` do not establish or conflict
with worktree identity. Adoption cannot create a replacement packet.

An Everything launch may name several tracker tickets. The command creates one
delivery task, work-item packet, and `autodev.json` per ticket under the shared
run. Resume one ticket with that packet's `--state`; never combine several
tickets into one mutable state file or restart the whole batch to repair one
item.

## Run evidence

Each run keeps an immutable request/snapshot, effective policy source list and
fingerprint, state/event ledger, decisions, validation, provider actions,
readback, final result, and unresolved gaps. Raw evidence follows routed
retention; compact receipts and the work-item packet survive Health.

Closeout owns provider reconciliation and the canonical `delivery_complete`
transition. Health starts only after that proof. It audits the required receipts
first, creates a resume manifest and a complete packet manifest, and freezes a
packet-local preflight. The packet manifest hashes every required packet file,
every file declared by `work.yml`, and every other durable packet file outside
Health's own output; it also proves `artifacts/`, `logs/`, and
`logs/conversations/` exist. The
physical gate re-hashes and parses the canonical task, requires exact
delivery/worktree/revision identity, JSON-compares packet Merge/Closeout
snapshots with canonical typed receipts, and verifies the complete ordered
non-Health stage audit and every stage snapshot hash. Before deletion it
rechecks every manifest hash. After the semantic move, every file must still
match its pre-cleanup hash except `work.yml` and `autodev.json`; those two may
change only to record the finished location/state and are parsed and validated
again. The target-local runtime readback binds that preflight hash. Physical worktree
removal consumes exact domain, project, worktree, preflight, and runtime-receipt
inputs; one atomic receipt binds both final resource dispositions. A separate
packet-local closed-worktree readback snapshots the exact registry row and is
checked against live `worktrees/closed.yml`, or records `not_managed`. Health
then preserves and moves the durable work-item packet to the finished lane. It
never performs a host-wide/all-resource container operation, and a
reopen/hold marker stops unattended cleanup. Health has a manual command and
skill; no schedule is enabled.

The Health preflight always records `dirty_disposition: clean_only`. Physical
worktree removal requires a clean `git status --porcelain`; a dirty checkout is
never disposable through Health. Preserve or reconcile dirty changes in a
separate operator workflow, make the checkout clean, then rerun Health with a
fresh preflight.

Managed runtimes are registered when the worktree is created. Their identity
template includes `{domain}`, `{project}`, and `{worktree}`, and both frozen
commands contain the rendered runtime identity. Health runs only those exact
commands. The teardown is followed by a fresh readback; the receipt must be no
more than 15 minutes old and the physical gate immediately runs the registered
readback again. Exit status 0 means the one registered worktree runtime is
absent. Any other exit status blocks worktree removal. No command may use
`--force`, a Git metadata sweep, host-wide container/volume/image/network
cleanup, an all-resources selector, a guessed name, or a shared runtime.

Provider readback must cover every item-owned durable surface, not only visible
containers. The LOS fast-worktree adapter binds the full declared runtime
identity to one registered Git worktree and proves its compose project,
including exact project-labeled/prefixed containers, networks, and volumes,
Postgres database, Redis namespace, Valkey namespace across every configured
logical cache database, registry row, and env
file are absent. Shared infra being down is a blocker because it prevents that
proof; silence from the ordinary LOS status display is never absence evidence.
The shared external LOS network is outside the project label/prefix selectors
and remains untouched.

![Auto-Dev Health lifecycle](assets/auto-dev-health.svg)

Development stage skills perform provider, code, test, review, merge, and
deployment work. `agentic-os develop stage` is deliberately only a recorder:
it accepts a complete set of `development-stage-evidence/v1` receipts, validates
them before the first transition, and never turns an assertion into an action.

Merge proof is intentionally typed. The completed `merged` receipt carries
`merge_sha`, provider-read `source_head_sha` equal to the reviewed
`subject_revision`, `provider`, `pull_request`, configured `repository`,
configured `base_branch`, provider-qualified `author_identity`, derived
`author_kind`, and `readback_verified: true`.
Health reuses that identity exactly: its terminal-authority provider/reference
equal the Merge provider/pull-request fields and its terminal revision equals
`merge_sha`.

The authority before Merge is also immutable. Finalize can authorize only a PR
whose provider-read author identity classifies as `ours` against the frozen
task authorship list, and it records `readiness_decision: ready_for_merge`
without merging. Review Others can authorize only an identity classified as
`others`, with `review_mode: review_no_merge` and `review_result: clean`.
Merge accepts the hashed completed receipt from exactly one of those owners and
requires its provider, PR, repository, base, reviewed revision, author identity,
and derived author kind to match the open/ready/merged provider chain.

`not_required` is a governed result, not a label. The decision uses
`auto-dev-stage-policy-decision/v1` and binds work item, canonical work id,
domain, project, stage, reason, decision maker, policy fingerprint, timestamp,
and a SHA-256 reference to the delivery run's exact frozen effective-policy
receipt. Recording copies both the policy source and decision into immutable,
packet-local hashed proof. The frozen project stage policy determines whether
`not_required` is legal. Detective, Create Artifacts, Document, Review Others,
QA, Finalize, and Release may be contextual or disabled. Delivery-managed
stages retain their own typed decision path. Develop, PR Create, Review Self,
Merge, Closeout, and Health are never silently skipped when they are inside the
active workflow.

## LOS Django QA child delivery

The LOS Django project stops Auto-Dev Everything at Merge; Release and Deploy
belong to the separate LOS release event. Ticket-level Document is currently
disabled by project policy but remains available to enable later.

When the application PR opens, Auto-Dev always creates a Jira QA Automation
Assessment subtask under the root Jira. The assessment may end in a typed skip
when browser automation adds no meaningful coverage. When it is required, the
subtask owns a child Auto-Dev delivery in
`Lenders-Cooperative/los-qa-automation`: analyze the application diff and the
Django `qa-analysis` skill, name the exact `tests/jira/<PARENT>/` spec and
README plus any pages/helpers/fixtures, create a branch and PR, run Playwright,
and bind the child PR and checks back to the parent. Direct pushes to `main` are
not part of this delivery. The parent QA gate waits for the configured child
completion or the accepted typed skip.

Once Health finishes, the completed packet is immutable history. A QA follow-up
does not edit it or reuse its old worktree/runtime. Run `agentic-os auto-dev
reopen --state <finished-packet> --run-id <new-id> --reason "<why>" --stage qa
--apply`. The command requires completed Health evidence plus a terminal/closed
canonical row, writes a reopen receipt into one new active packet, and starts a
fresh delivery run, worktree, and runtime registration. A direct canonical
state edit is rejected if it still points to `03-complete`; the old packet and
Health manifests remain the audit trail.

## Failure model

Classify failures before retrying. Provider/VPN/environment unavailability
pauses and resumes from the same receipt. Code, test, validation, target, or
readback failures stay with the owning workflow. Missing product/security/
architecture decisions block with one exact owner action. Never restart by
deleting state or create duplicate external artifacts to escape a pause.

## How to tell the program is healthy

Healthy means: routing selects the intended workflow, effective policies are
explainable, every active run advances or names a blocker, external effects have
readback, stale/duplicate compatibility surfaces are shrinking, and a fresh
agent can resume from receipts without chat history.

See `ARCHIVE_SOON.md` for overlap disposition and `runbook.md` for operation.
