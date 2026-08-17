# Auto-Dev: everything

Use `/auto-dev-everything` to take one tracker item from current live truth
through every applicable Auto-Dev stage. Everything is an orchestrator over the
same-named stage workflows. It does not duplicate their logic, state, approvals,
or provider authority.

## Initialize or resume

1. Route the tracker item to the narrowest domain, project, and repository.
2. Find the existing canonical work item and Development Delivery task.
3. Create state only when no matching item exists; otherwise resume the same
   packet and `autodev.json`.
4. Resolve and freeze the effective root, domain, project, and invocation policy
   sources and fingerprint.
5. Read completed stages, blockers, holds, exact provider identities, worktree,
   runtime registration, and next action before scheduling any work.

## Exact stage order

| # | Stage | Expected terminal boundary |
| --- | --- | --- |
| 1 | Grooming | implementation-ready tracker truth or blocker |
| 2 | Detective | evidence-backed conclusion or explicit missing evidence |
| 3 | Create Artifacts | validated local output and required provider readback |
| 4 | Readiness | exact repository/base/policy/worktree/plan resolved |
| 5 | Develop | `local_validation` |
| 6 | Document | canonical documentation validated/read back |
| 7 | PR Create | required pull-request family created and provider-verified |
| 8 | Review Self | exact revision ready for Finalize or blocker |
| 9 | Review Others | clean no-merge review or actionable findings |
| 10 | QA | every applicable gate passed, failed, or blocked |
| 11 | Finalize | governed `ready_for_merge` decision for our work |
| 12 | Production Release Validation | read-only release-family and evidence validation before Merge |
| 13 | Merge | provider-read merged result and `merge_sha` |
| 14 | Release | exact published version/artifact readback |
| 15 | Deploy | exact artifact verified in target environment |
| 16 | Closeout | `delivery_complete` provider/tracker reconciliation |
| 17 | Health | audited finished packet and exact resource disposition |

PR Create is stage 7. Its lower-level Development Delivery recorder remains
`release_propagation` for compatibility, and the legacy
`/auto-dev-release-propagation` command delegates to PR Create family mode.
Neither compatibility surface is a separate Auto-Dev stage.

No project, policy overlay, automation, or agent may reorder these rows. A
stage that truly does not apply remains visible in `autodev.json` with the
strict typed decision bound to the frozen policy, work item, decision maker,
reason, and time. Never omit a row or use `not_required` to avoid missing
evidence.

## Orchestration behavior

The coordinator selects only the next eligible incomplete stage and invokes its
same-named workflow. It may use subagents inside that stage for bounded parallel
work, but it records one reconciled outcome and does not let parallel execution
cross an approval or predecessor boundary.

After every stage:

- validate the typed receipt and exact subject revision/target;
- append the work log and plain-English next action;
- refresh `autodev.json` from canonical delivery state;
- re-read provider or runtime truth when the stage mutated it;
- stop if the result is failed, blocked, changed by another actor, or awaiting
  approval.

Use quiet artifact-backed runners and watchers for long tests, CI, reviews,
deployments, and provider waits. The chat should receive terminal evidence,
real blockers, behavior-changing decisions, or requested status—not heartbeats.

## Recovery and multi-ticket runs

On a failure, preserve the packet, classify the failure, and resume at the same
stage after the smallest safe correction. Do not skip forward, recreate state,
erase a receipt, or rerun a provider mutation whose outcome has not been read
back.

A command may name several tickets, but each gets its own task, packet,
worktree/runtime registration, `autodev.json`, receipts, and lifecycle. Parallel
ticket execution may share orchestration capacity, never mutable state. Resume
one ticket from its own `--state`; do not collapse the batch or duplicate
completed siblings.

## Done criteria

Everything is complete only after Health validates the receipt/packet manifest,
records exact worktree and runtime dispositions, refreshes active state, and
moves the durable packet to the finished lane. `absent` and `not_managed` are
valid explicit resource outcomes; missing proof is not.

No schedule is enabled by this command. A future automation may call this exact
manual entrypoint and state contract, but it must not own a second queue,
lifecycle, cleanup policy, or packet format.
