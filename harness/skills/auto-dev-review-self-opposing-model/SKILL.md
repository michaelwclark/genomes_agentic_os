---
name: auto-dev-review-self-opposing-model
description: Run the canonical full Auto-Dev review flow for one existing work item, using the configured independent opposing model and receipt-backed readiness evidence.
---

# Auto-Dev Review Self Opposing Model

Use this skill for `$auto-dev-review-self-opposing-model <TICKET>` from either
Claude or Codex. It is the only manual or agent-invoked path for the
opposing-model checkpoints within `$auto-dev-review-self` and
`$auto-dev-review-repair`.

1. Resolve the existing Auto-Dev work item by ticket and read its tracker,
   PR Create family receipt, project review policy, source worktree, and current
   provider state. Refuse an ambiguous ticket, absent PR family, wrong target,
   stale head, or unavailable canonical worktree.
2. Select the required independent model family from proven builder identity.
   For an Anthropic reviewer, use only the installed `claude` CLI with
   CLI-native authentication; remove `ANTHROPIC_API_KEY` and
   `ANTHROPIC_AUTH_TOKEN`. Never substitute API/SDK transport or an unreviewed
   model family.
3. Run the complete `$auto-dev-review-repair` flow around the selected review
   checkpoint: required local validation, exact PR-family/provider readback,
   quiet CI and thread repair where applicable, then pre-PR or post-PR review.
   This skill may repair only through that owner and must return to the original
   builder for actionable findings.
4. Run the canonical executable; it resolves the ticket, exact worktree, PR
   provider readback, selected native reviewer, and receipt directory:

```bash
python3 harness/skills/auto-dev-review-self-opposing-model/scripts/run_opposing_model_review.py \
  <TICKET> --os-root <agentic-os-root>
```

5. Require the resulting `review-request.json`, `reviewer-response.md` when
   available, `model-receipt.md`, `review-ledger.jsonl`, and
   `readiness-decision.json`. A timeout, auth failure, empty output, or malformed
   output is a sanitized receipt-backed unavailable/runtime result, never a
   clean review. Honor the project's block policy.
6. Record the typed review-stage evidence only after the deterministic decision
   is clean and all exact-head CI/thread gates are satisfied. A post-PR clean
   review alone does not grant merge authority; `$auto-dev-merge` remains the
   sole merge owner.

Do not hand-craft a Claude/Codex prompt, create a second PR, force-push, bypass
required checks, or treat unavailable review as approval.
