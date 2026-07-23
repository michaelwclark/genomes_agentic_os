---
name: auto-dev-finalize
description: Converge every open agent-authored PR for one tracker ticket through independent review, CI and review repair, branch-family parity, and a governed merge-readiness decision. Manual kickoff only.
---

# Auto-Dev Finalize

This is the canonical endgame for our own PR family. It is manually invoked;
no schedule or automatic opened-PR trigger is enabled.

1. Read the live tracker item, project GitFlow policy, open PRs, exact head/base
   SHAs, checks, reviews, and existing receipts. Group the family by exact
   tracker key and prove every required target.
2. Resolve merge intent from an explicit run override, then project policy,
   then one direct operator decision. Per-PR and whole-family opt-outs win, but
   Finalize records the decision and never executes the merge.
3. Require a reviewer from the opposing model family for agent-authored work.
   Never let the implementation model approve its own result.
4. Run bounded, quiet assessment and repair rounds. Re-read all automated and
   human threads after every push. Resolve bot findings only after a fix or a
   factual false-positive reply; never resolve human threads.
5. Declare the family ready only when every required PR has current green
   checks, clean actionable threads, acceptance evidence, branch parity, and
   required reviews.
6. Record the converged PR-family decision with `agentic-os auto-dev record
   --stage finalize`. Provider readback must include provider, pull request,
   configured repository and base branch, reviewed head, provider-qualified
   `author_identity`, derived `author_kind: ours`,
   `readiness_decision: ready_for_merge`, and `readback_verified: true`.
   Classify the author against the frozen `task.authorship.ours` list; never
   accept a caller-selected author kind. Hand the immutable packet-local
   receipt and its SHA-256 to Auto-Dev Merge. Merge alone revalidates live
   provider truth, executes the authorized mutation, reads it back, and records
   the separate `merge` stage.

Deployment, delivery reconciliation, and lifecycle cleanup belong to Auto-Dev
Deploy, Closeout, and Health respectively. If merge is not
authorized, stop at `ready_for_merge` with the exact next action.
