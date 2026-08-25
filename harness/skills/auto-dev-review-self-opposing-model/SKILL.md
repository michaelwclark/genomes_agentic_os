---
name: auto-dev-review-self-opposing-model
description: Execute or reuse the single canonical full Auto-Dev review, or a bounded delta verification explicitly requested by Review Repair, using the configured independent opposing model and stable keyed receipts.
---

# Auto-Dev Review Self Opposing Model

Use this skill for `$auto-dev-review-self-opposing-model <TICKET>` from either
Claude or Codex. It is the only manual or agent-invoked path for the
opposing-model transport. Review Self alone may request `full`; Review Repair
may request only `delta` with a canonical parent key.

1. Resolve the existing Auto-Dev work item by ticket and read its tracker,
   PR Create family receipt, project review policy, source worktree, and current
   provider state. Refuse an ambiguous ticket, absent PR family, wrong target,
   stale head, or unavailable canonical worktree. Search only canonical domain
   and `harness/shared_factory` project surfaces. On the initial full review,
   when no earlier finishing-review request exists, derive the request from the
   immutable PR Create provider readback and frozen packet policy identity;
   never guess a PR, base, head, or policy value.
2. Select the required independent model family from proven builder identity.
   For an Anthropic reviewer, use only the installed `claude` CLI with
   CLI-native authentication; remove `ANTHROPIC_API_KEY` and
   `ANTHROPIC_AUTH_TOKEN`. Never substitute API/SDK transport or an unreviewed
   model family.
3. Build the stable review subject from repository, PR, exact base/head,
   effective policy fingerprint, scope, and purpose. Claim or join that key
   before invoking a model. Reuse a terminal exact-key receipt. Never use model
   identity as part of the key and never use another reviewer to bypass reuse.
   All stage aliases normalize to the single `review_self` purpose and the
   `full-pr` scope. Every entrypoint uses `<agentic-os-root>/state/review-coordination`;
   work-item and `--output-dir` paths hold artifacts only and cannot create a
   fresh budget family.
4. Execute only the requested mode. `full` produces the canonical findings
   ledger. `delta` reviews only changes since its canonical parent and appends
   findings without rereading the full original diff.
5. Run the canonical executable; it resolves the ticket, exact worktree, PR
   provider readback, selected native reviewer, and receipt directory:

```bash
python3 harness/skills/auto-dev-review-self-opposing-model/scripts/run_opposing_model_review.py \
  <TICKET> --os-root <agentic-os-root>
```

When `--os-root` is omitted, the runner accepts only `AGENTIC_OS_ROOT` or the
installed `~/agentic_os` root after marker/directory validation. It never uses
the current worktree as a private coordination root, and an explicit root that
disagrees with `AGENTIC_OS_ROOT` fails closed.

6. Require the resulting `review-request.json`, `reviewer-response.md` when
   available, `model-receipt.md`, `review-ledger.jsonl`, and
   `readiness-decision.json`. A timeout, auth failure, empty output, or malformed
   output is a sanitized receipt-backed unavailable/runtime result, never a
   clean review. Honor the project's block policy.
7. Record the typed review-stage evidence only after the deterministic decision
   is clean and all exact-head CI/thread gates are satisfied. A post-PR clean
   review alone does not grant merge authority; `$auto-dev-merge` remains the
   sole merge owner.

Budgets are one normal full review, at most three deltas, two absolute full
reviews per family, and one provider post. Exhaustion is a receipt-backed block
raised before a model/provider call. Provider output is terminal-only, carries
`<!-- agentic-os-review:<key> -->`, re-reads the head after the model returns,
and reuses provider readback only when that exact hidden marker line exists.
Only a structured clean verdict that passes the provider scrub is posted;
findings remain canonical local receipts without a post, including findings
that fail the scrub. A clean verdict that fails the scrub is stored as a
retryable `unavailable` attempt for the same key instead of consuming the one
canonical full-review receipt. Both transports parse only the final non-empty
`AGENTIC_OS_REVIEW_VERDICT: CLEAN|FINDINGS` line, so an echoed prompt cannot
manufacture or invalidate the reviewer verdict. Both transports define CLEAN
as no unresolved blocking findings. An active top-level `BLOCKER` section or a
JSON finding with `blocking: true` contradicts CLEAN and becomes canonical
findings. Resolved/prior sections and non-blocking WARNING/FYI or low findings
may coexist with CLEAN. Every fenced JSON findings array is inspected, so a
later empty example cannot erase an earlier blocker.

Do not hand-craft a Claude/Codex prompt, create a second PR, force-push, bypass
required checks, treat unavailable review as approval, or post intermediate
findings to the provider.
