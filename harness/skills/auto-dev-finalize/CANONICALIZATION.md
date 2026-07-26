# Canonicalization: PR Review / Finalize Surfaces

> PLAN OF RECORD (2026-07-18): Michael confirmed the consolidation direction
> and expanded it into the PR & SDLC Program Consolidation Plan at
> `domains/clarks_consulting/02-projects/genomes_agentic_os/work-items/02-active/063_pr_sdlc_program_consolidation_plan/`
> (Notion projection: pr_sdlc_consolidation_plan surface). That plan
> supersedes the verdict table below as decisions land; this file remains
> the seeding decision record.

Decision record for making `auto-dev-finalize` the canonical owner of
"drive one ticket's full gitflow PR family to merged". Reviewed 2026-07-17.
Verdicts: KEEP (distinct mission or building block), CONSUMED (called by
finalize), OVERLAP (operator decision requested).

| Surface | Where | Mission | Verdict |
| --- | --- | --- | --- |
| `auto-dev` | harness skill + program layer | Full SDLC runner, ticket to PR, single-PR post-PR loop | KEEP. Now hands the multi-target family endgame to finalize at `pr_open` (cross-reference landed in its SKILL.md). |
| `develop` | harness skill | Canonical 1-N delivery incl. release propagation (creates the cherry-pick PRs) | KEEP. Seam: develop creates family PRs; finalize drives them to merged. |
| `quiet-workon-orchestrate` | harness skill | Implementation orchestration, quiet chat, holdouts | KEEP / CONSUMED. Finalize fix waves follow its contracts. |
| `watch-pr-quiet` | harness skill | File-based CI watch primitive | CONSUMED. |
| `finishing-touches-review` | harness skill | Deterministic cross-model review engine | CONSUMED (quality-gate transport option). |
| `pull-request` | harness skill | Graybeard review battery, findings + GitHub comments | CONSUMED by Phase 5. Review-only; no finalize scope. |
| `pull-request-*-reviewer` agents + `pull-request-graybeard` | Claude agents | Dimension reviewers | CONSUMED by Phase 5. |
| `pr-review` | `~/.claude/skills/pr-review` | Findings-first PR review (personal skill) | OVERLAP with `pull-request`. Two review entrypoints with the same stance. Recommend merging into `pull-request` (or retiring `pr-review`) so review has one canonical entrypoint. Operator decision. |
| `copilot-preview-review` (`cpreview`) | `~/.claude/skills` | Pre-PR local Copilot CLI review of the current branch | KEEP. Different stage (pre-PR, local diff); feeds the write side, not finalize. |
| Repo-local `copilot-fix` / `copilot-hell` | LOS repo skills | Per-PR Copilot triage/fix/reply/resolve rounds | CONSUMED. Finalize prefers them; GraphQL fallback lives in the skill. |
| `os-cleaner` / `os_cleanup` workflow | shared_factory | Post-merge worktree/work-item reconciliation | CONSUMED at closeout. |
| `pr_watch_repair_loop` workflow | `domains/los/03-workflows/engineering` | Single-PR quiet CI/Copilot watch + repair to merge-ready, stops before approval/merge | OVERLAP (superseded at family scope). Finalize's Phases 3-4 are this loop generalized to N PRs plus quality gate and merge gate. Recommend: keep as the single-PR building block referenced by auto-dev, or retire in favor of pointing at finalize with a one-PR family. Operator decision. |
| `post_merge_jira_routing` workflow | `domains/los/03-workflows/engineering` | Post-merge Jira terminal routing (Ready for QA vs Ready for Release) with registry/sibling guards | KEEP / CONSUMED. Finalize Phase 7 delegates the terminal Jira status to it; finalize never hard-codes Done. |
| `pr_fleet_monitor` / `multi_jira_finishing_qa` workflows | `domains/los/03-workflows/engineering` | Fleet observation; cross-ticket finishing QA | KEEP. Observation and cross-ticket QA sit beside finalize (per-ticket family driver); no mission collision. |
| `los_pr_health` program + `team_prs_board` / `active_prs_board` automations | los | Observation boards and snapshots | KEEP. Observation only; no mission collision. |
| AUTO - LOS Agentic PR Maintenance | `domains/los/04-automations/engineering/agentic_pr_maintenance` | Every-15-min automated driving of open LOS PRs | OVERLAP. This is an automated finalize-lite and can collide with a manual finalize run on the same PRs (advancing-SHA contention already observed historically). Recommended: (1) short term, the finalize run's concurrent-driver guard stands down lanes the automation is actively pushing, and the operator pauses one side for the family being finalized; (2) long term, converge by making the automation a scheduled adapter that invokes this skill's protocol per PR family, so there is one policy source. Operator decision. |

Rules of the road going forward:

- New PR-finalization behavior (gates, loop bounds, merge policy handling,
  closeout) lands in `auto-dev-finalize` first; other surfaces adapt or call
  it.
- Review skills stay review-only. Anything that fixes, resolves, or merges
  belongs to finalize or the implementation skills it dispatches.
- The write side and review side share one gate list
  (`QUALITY-GATES.md` + project addendum); neither side forks its own copy.
