# Auto-Dev: shared operating rules

Auto-Dev is one program with individually callable workflows. Start a complete
run with `/auto-dev-everything`, or invoke one same-named stage command or skill
when only that part of the lifecycle is needed. All stages use the same work
item and canonical Development Delivery state.

## Start or resume

Before acting:

1. route to the narrowest domain and project;
2. identify the tracker item or canonical work-item id;
3. search canonical active state before scanning folders;
4. reuse the existing packet, `autodev.json`, task, worktree, provider
   references, receipts, logs, and artifacts;
5. resolve root, domain, project, and invocation policy and record its sources
   and fingerprint;
6. read the latest work log, next action, blocker, and stage receipt.

Never create another packet, branch, pull request, worktree, or runtime merely
because the existing run is confusing or blocked. First reconcile the existing
identity and state.

## Canonical lifecycle

The runtime order is:

1. Grooming
2. Detective
3. Create Artifacts
4. Readiness
5. Develop
6. Document
7. PR Create
8. Review Self
9. Review Others
10. QA
11. Finalize
12. Production Release Validation
13. Merge
14. Release
15. Deploy
16. Closeout
17. Health

PR Create is the only Auto-Dev stage that resolves and creates the required
pull-request family. The lower-level Development Delivery recorder still uses
`release_propagation` for compatibility, and `/auto-dev-release-propagation`
delegates to PR Create. Neither compatibility surface adds another Auto-Dev
stage or moves PR creation later in the lifecycle.

The order is exact for an Auto-Dev item. A stage can be called independently,
but a later external stage still requires every applicable predecessor to be
terminal and receipt-backed. A domain or project may specialize a stage; it
may not reorder the lifecycle or transfer one stage's authority to another.

## Orchestration and subagents

The coordinator owns the work-item identity, effective policy, plan, approvals,
stage transition, provider target, evidence judgment, and final response. Use
subagents for bounded work that can run independently, such as repository
mapping, evidence gathering, one isolated implementation area, focused tests,
or independent review.

For every delegation:

- state the exact question or deliverable;
- provide only the context needed for that task;
- assign file or module ownership for edits;
- tell the worker that other agents may be editing concurrently;
- require a compact result with evidence, changed files, checks, and blockers;
- review the result before recording stage completion.

Subagents do not inherit merge, deploy, production, destructive, or external
write authority. Parallelism never relaxes ordering or approval gates.

## Evidence, work logs, and chat

Record material actions in the packet work log using plain English: what was
attempted, why, what changed, what evidence was produced, and what happens next.
Store commands, structured outcomes, hashes, provider identifiers, exact
revisions, and readbacks in typed receipts. Put long logs in the packet's
`logs/` or `artifacts/` directory and reference them from the compact receipt.

A claim is only as strong as its evidence boundary. Say `local_validation`,
`ready_for_merge`, `merged`, `released`, `deployed`, or `delivery_complete`
only when the matching stage produced its required receipt. Do not turn one
boundary into another in prose.

For long tests, builds, CI, watches, or deployments, use quiet artifact-backed
execution. Do not stream repeated unchanged status into chat. Report only a
decision, a blocker, a requested status, or a terminal result backed by the
exact command, check, job, or receipt.

## Recovery

When something fails:

1. stop advancing the stage;
2. preserve state and capture the failure evidence;
3. classify it as code, test, configuration, access, provider,
   infrastructure, policy, or product-decision failure;
4. compare the frozen task with current live truth and policy drift;
5. make the smallest safe correction;
6. rerun only the affected validation before resuming.

Do not erase receipts, rewrite history, silently change repository or base,
force cleanup, or downgrade a failed/unavailable check to passing. Repeated
failure without new evidence becomes one explicit blocker and next action.

## Approval and output safety

Pause instead of guessing at product decisions, missing access, security
questions, unresolved ownership, provider ambiguity, merge authority,
deployment, production, destructive work, billing, legal records, or
customer-visible output. External output must follow its artifact contract and
must be sanitized for the audience before apply and readback.

`not_required` is not a prose shortcut. It requires a typed policy decision
bound to the work item, stage, frozen policy fingerprint and source hash,
decision maker, reason, and verification time.

Finished packets are immutable. Follow-up work uses the canonical reopen flow,
which creates a new delivery run and preserves the completed packet as evidence.
