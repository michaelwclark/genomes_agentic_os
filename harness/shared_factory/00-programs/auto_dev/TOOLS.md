# Auto-Dev Tools

## Manual workflow entrypoints

| Need | Command or skill | Result |
| --- | --- | --- |
| Full implementation delivery | `/auto-dev` or `agentic-os develop start ...` | state/worktree/quality/release receipts |
| Readiness/context stage | `/auto-dev-readiness` then `agentic-os develop stage ... --stage readiness` | verified context and `planned` state |
| Isolated implementation stage | `/auto-dev-implementation` then `develop stage --stage implementation` | code/test receipts and `local_validation` |
| Test/review/PR repair stage | `/auto-dev-review-repair` then `develop stage --stage review` | provider readbacks and `ready_for_merge` |
| Release propagation stage | `/auto-dev-release-propagation` then `develop stage --stage release_propagation` | target matrix or policy-backed `not_required` receipt |
| Merge/deploy/cleanup stage | `/auto-dev-closeout` then `develop stage --stage closeout` | authoritative closeout and `delivery_complete` |
| Effective code/QA/gitflow policy | `agentic-os develop policy ...` | ordered sources and fingerprint |
| Excellent provider artifact | `/auto-dev-create-artifacts` or `agentic-os artifacts ...` | native draft, validation, apply/readback receipts |
| Deep bug/RCA investigation | `/auto-dev-detective` or `agentic-os detective ...` | versioned evidence packet and report |
| Others' PR review | `/pull-request` | blocker-focused review receipt |
| Effective inherited OS rules | `agentic-os rules effective ...` | strictest-wins rule projection |

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
