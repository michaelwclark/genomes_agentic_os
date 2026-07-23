# Implementation Plan: OS cleanup

## Metadata

| Field | Value |
| --- | --- |
| Domain | `shared_factory` |
| Lane | `engineering` |
| Owner | `Agentic OS` |
| Created | `2026-07-20` |
| Last Reviewed | `2026-07-20` |

## Outcome Link

- See `outcome-brief.md` for the definition of done.

## Execution Stages

| Stage | Scope | Acceptance Criteria | Risks |
| --- | --- | --- | --- |
| 1. Prove delivery | Read existing state and typed provider-read Merge proof. | `delivery_complete`; reviewed source head, provider, PR reference, merge SHA, and matching Health authority; no unresolved hold. | A stale tracker state is mistaken for merge proof. |
| 2. Preserve recovery | Audit receipts, copy useful local evidence, and write the resume manifest. | Every required receipt is readable and hashed; recreation steps are clear. | Evidence disappears with the checkout. |
| 3. Preflight resources | Freeze exact registered worktree, runtime, authority snapshots, and receipt hashes in `auto-dev-health-preflight/v1`. | Managed root, safe branch, clean Git status, no `REOPEN.md`, item-local runtime, immutable packet-local gate. | Ambiguous ownership or dirty work affects unrelated or unpreserved changes. |
| 4. Reconcile resources | Record runtime readback bound to the preflight, then remove the linked worktree with all five scoped inputs. | Runtime receipt matches `preflight_sha256`; one atomic resource receipt records both dispositions; packet-local closed-worktree readback matches live registry state; failures remain registered. | Early registry closure or stale proof hides a failed removal. |
| 5. Finish durable state | Move the packet, update canonical work, clear reconstructable pointers, refresh indexes. | Packet and state are finished and inactive with history receipt. | Packet and database paths drift apart. |
| 6. Validate and record | Read back all surfaces and record strict Health evidence. | Validation passes, residual holds are empty, packet remains readable. | A partial outcome is reported as complete. |

## Files / Systems In Scope

| Path Or System | Change Type | Notes |
| --- | --- | --- |
| Existing work-item packet | preserve and move | Markdown, logs, artifacts, `autodev.json`, audit, and manifest remain durable. |
| Exact project worktree | remove when eligible and clean | Use Git worktree removal; never raw deletion of a linked checkout. |
| Exact item-local runtime | stop/remove when eligible | Use target-local teardown only. |
| Worktree registry and canonical work state | reconcile | Mutate only after the corresponding physical operation succeeds. |
| Active projections | refresh and read back | Finished work must no longer appear active. |

## Dependencies And Assumptions

- Auto-Dev Closeout already proved `delivery_complete`.
- Project development and environment-access policy identify the managed root,
  protected branches, runtime definition, and any retention rule.
- The operator can read terminal provider truth and local Git metadata.

## Risk Register

| Risk | Impact | Mitigation | Stop Condition |
| --- | --- | --- | --- |
| Wrong checkout removed | high | Match item, repository, managed root, branch, registry, merged pull request, and exact merge revision. | Any identity mismatch. |
| Dirty changes lost | high | Require clean `git status --porcelain`; reconcile changes in a separate operator workflow and rerun Health. | Any dirty or untracked file. |
| Shared runtime stopped | high | Require unique mapping to the target checkout. | Runtime ownership is ambiguous. |
| Recovery evidence lost | high | Copy, hash, and read back receipts before cleanup. | Audit or manifest is incomplete. |
| Reopened work hidden | high | Treat `REOPEN.md` and residual holds as blockers. | Any hold exists. |
| Registry lies about removal | medium | Close entry only after successful runtime/Git action. | Teardown or removal fails. |

## Validation Plan

| Check | Command Or Evidence | Required |
| --- | --- | --- |
| Exact cleanup scope | Item-scoped `cleanup-closed --dry-run` with domain, project, worktree, Health preflight, and runtime receipt | yes |
| Bound resource readback | `auto-dev-runtime-cleanup/v1`, atomic `auto-dev-resource-cleanup/v1`, and audited `auto-dev-closed-worktree-readback/v1` | yes |
| Finished packet | `project work-item set` and packet readback | yes |
| Canonical finished state | `work set`, `work show`, and history receipt | yes |
| Active projections | `project work-item sync-active` and `work active-now` readbacks | yes |
| OS structure | `agentic-os validate` summary | yes |

## Orchestration Split

| Step | Layer | Why |
| --- | --- | --- |
| Receipt hashes and schema checks | deterministic validation | Exact, repeatable proof. |
| Terminal and resource readback | provider/Git/runtime tools | Live facts must not be inferred. |
| Resume-manifest summary | agent judgment | The recovery path must be concise and understandable. |
| Destructive boundary | approval rules | Resource removal requires explicit safety gates. |

## Dispatch Plan

| Dispatch | Owner | Files Or Responsibility | Verification |
| --- | --- | --- | --- |
| Delivered-item lifecycle | `$auto-dev-health` | One existing Auto-Dev packet and strict final receipt. | Health evidence accepted from completed packet. |
| General bounded reconciliation | `$os-cleaner` | Exact candidate set and cleanup receipts. | Removed/skipped registry readback. |
| Merge/deploy/provider closeout | Auto-Dev Merge, Deploy, and Closeout | Delivery truth before Health. | `delivery_complete` receipt. |
