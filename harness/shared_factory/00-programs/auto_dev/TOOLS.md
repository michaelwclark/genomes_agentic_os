# Auto-Dev Tools

## Manual workflow entrypoints

| Need | Command or skill | Result |
| --- | --- | --- |
| Bare Auto-Dev development delivery | `/auto-dev` or `agentic-os auto-dev default ...` | project Default window, always through PR Create or later |
| Project-relative full delivery | `/auto-dev-everything` or `agentic-os auto-dev everything ...` | configured Everything window and one `autodev.json` plus delivery/provider receipts |
| One named workflow | `agentic-os auto-dev <verb> ...` and the matching skill | resumable single-stage state |
| Grooming | `/auto-dev-grooming` | implementation-ready source of truth |
| Deep bug/RCA investigation | `/auto-dev-detective` or `agentic-os detective ...` | versioned evidence packet and report |
| Excellent provider artifact | `/auto-dev-create-artifacts` or `agentic-os artifacts ...` | native draft, validation, apply/readback receipts |
| Readiness/context stage | `/auto-dev-readiness` then `agentic-os develop stage ... --stage readiness` | verified context and `planned` state |
| Isolated implementation stage | `/auto-dev-develop` (canonical owner: `/auto-dev-implementation`) then `develop stage --stage implementation` | code/test receipts and `local_validation` |
| Code and issue documentation | `/auto-dev-document` | verified audience-specific documentation |
| PR family creation | `/auto-dev-pr-create` then compatibility recorder `develop stage --stage release_propagation` | target matrix and provider-read family receipt projected as `pr_create` |
| Test/review/PR repair stage | `/auto-dev-review-self` (canonical owner: `/auto-dev-review-repair`); use `/auto-dev-review-self-opposing-model <TICKET>` for each independent-model checkpoint, then `develop stage --stage review` | review of the exact PR Create family and `ready_for_merge` |
| Others' PR review | `/auto-dev-review-others` (`/pull-request` is compatibility) | clean review-only receipt with provider authorship |
| Standalone QA | `/auto-dev-qa` | exact revision/acceptance evidence |
| Legacy release propagation invocation | `/auto-dev-release-propagation` | compatibility alias to PR Create family mode |
| Our PR-family endgame | `/auto-dev-finalize` | independently reviewed, converged PR family and readiness-only receipt |
| Governed merge router | `/auto-dev-merge` then `develop stage --stage merge` | merge SHA, reviewed-head/provider/PR readback, or explicit hold |
| Version/tag/package release | `/auto-dev-release` | verified release receipt |
| Deployment | `/auto-dev-deploy` then `develop stage --stage deploy` | exact deployed-version proof or policy skip |
| Provider/delivery reconciliation | `/auto-dev-closeout` then `develop stage --stage closeout` | authoritative closeout and `delivery_complete` |
| Final lifecycle hygiene | `/auto-dev-health` or `agentic-os auto-dev health ...` | audited receipts, resume manifest, bounded cleanup dispositions, and preserved finished packet |
| Post-Health QA/development follow-up | `agentic-os auto-dev reopen --state <finished-packet> --run-id <new-id> --reason <why> --apply` | immutable old packet plus one receipt-backed fresh packet/run/worktree/runtime registration |
| Effective program/access/code/QA/gitflow policy | `agentic-os develop policy ...` | ordered sources and fingerprint |
| Effective inherited OS rules | `agentic-os rules effective ...` | strictest-wins rule projection |
| Object Library source/install lifecycle | `$object-library` plus `agentic-os library` list, show, install, verify-install, and doctor | source build/release evidence plus receipt-backed installed projection readback |
| Managed Auto-Dev admission and observation | `agentic-os runtime submit`, `runtime status`, and `runtime snapshot` | named queue admission plus canonical worker, attempt, retry, dead-letter, and terminal receipts |

## Provider routes

Use the final routed layer's `TOOLS.md` for the currently registered Jira,
Linear, Notion, Confluence, GitHub, Slack, observability, memory, VPN/runtime,
and filesystem adapters. Resolver/renderer code does not own authentication.

External provider apply follows: typed approval receipt → typed target
verification → provider-adapter payload → provider tool → normalized live
readback receipt → engine-verified content hash/identity. Only Jira payloads are
native ADF; other providers receive explicit adapter payloads. A provider
response without readback is not completion.

Detective source transport follows: `detective resolve` → deployed-version
authority receipt → declared local/live source adapter → `record-evidence`.
Undeclared sources require a policy overlay before run start. When VPN or a
provider is unavailable, use `detective pause` once and `detective resume` with
a verified `investigation-availability/v1` probe receipt; do not loop transport
failures.

Health delegates cleanup to the canonical OS cleanup surfaces. Run their
receipt audit, full packet manifest, and packet-local Health preflight first.
Runtime teardown and fresh immediate exit-0-means-absent readback use only the
frozen identity-bound commands for the domain/project/worktree identity.
Worktree removal is limited to one registered id/path/branch/HEAD and requires
exact domain, project, worktree, preflight, and runtime-receipt inputs. Preserve
both readbacks in one atomic receipt. Do not force, sweep metadata, select
host-wide/all resources, guess, or touch a shared resource. The durable packet moves to finished; all
hashes remain exact except validated semantic `work.yml`/`autodev.json` updates.
