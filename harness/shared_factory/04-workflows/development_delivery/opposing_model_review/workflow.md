# Auto-Dev Opposing-Model Review

## Purpose

Provide one receipt-backed opposing-model review route for both Claude and
Codex harnesses. The workflow is invoked as
`$auto-dev-review-self-opposing-model <TICKET>` and is consumed by the existing
Auto-Dev Review Self/Review and Repair lifecycle.

## Flow

1. Reconcile the ticket, work item, PR Create family, canonical worktree,
   provider PR snapshot, and exact head SHA.
2. Prove builder identity and select the policy-required independent reviewer.
3. Prepare `artifacts/finishing-touches/<run-id>/` with the request and
   validation plan.
4. Execute the selected read-only reviewer through its approved native
   transport; Anthropic review uses the installed Claude CLI and CLI-native
   auth only.
5. Ingest a structured response or produce a sanitized unavailable/runtime
   receipt. Empty, malformed, timed-out, or unavailable output is never clean.
6. Use the deterministic finishing-review helper to compute the readiness
   decision, return findings to the builder, and let Review and Repair own all
   repair/CI/thread convergence.

## Boundaries

This workflow neither creates nor changes a PR target, pushes code, merges,
releases, or deploys. It does not replace the final provider-read merge gate.
