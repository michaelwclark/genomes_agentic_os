# /auto-dev-finalize

Review and finalize every open gitflow PR for one tracker ticket until merged
or explicitly blocked. Manual kickoff only; never scheduled or chained from an
automation.

`/auto-dev-finalize <TICKET> [--prs n,n,...] [--merge-authorized] [--max-rounds n] [--rounds-only n]`

The runner follows `harness/skills/auto-dev-finalize/SKILL.md`: discover the
ticket's full PR family from the routed project's gitflow targeting rule and
branch registry, fan out one read-only assessment subagent per PR (checks,
Copilot threads, migration audit against that PR's own base branch, tracker
acceptance map, quality findings, cherry-pick parity), consolidate findings on
the main thread, fix in per-PR worktrees, reply to and resolve bot threads
(never resolve human threads), re-watch through quiet file-based watchers, and
loop because every push re-triggers CI and Copilot.

Merge executes only when the project merge policy and an explicit operator
authorization both allow it; the default terminal state is `ready_for_merge`
with every gate green on every family PR. Closeout posts scrubbed tracker
comments, transitions the tracker per project config, updates the canonical
work item, and records run receipts.

DEV_STANDARDS: load the routed project's ordered
`dev_factory.dev_standards.paths` folders. The compatibility pointers at
`harness/skills/auto-dev-finalize/QUALITY-GATES.md` and the routed project's
`config/code-quality-gates.md` explain the migration (write side and review
side share the same list).
