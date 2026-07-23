---
name: pr-review
description: Canonical review, report, and authorized review-plus-merge workflow for other authors' pull requests. Use for one PR, batch verdicts, engineering-health reports, and guarded standard merges.
argument-hint: "<PR|URL|batch> [--mode review|report|review+merge] [--post|--no-post] [--no-merge] [--quick] [--severity critical|high|medium|low] [--jira-only|--acceptance-only] [--security] [--team-health on|off]"
---

# PR Review

This is the one canonical workflow for reviewing another author's pull
request. It combines blocker-focused review, tracker acceptance, target-branch
coverage, optional engineering-health reporting, and an authority-gated clean
merge. It does not own reviews or merges for our own agent-authored PRs.

## Modes

- `review`: produce verified findings and one final action for a single PR.
- `report`: produce batch verdicts and aggregate health signals; never merge.
- `review+merge`: review first, then use the normal project merge path only
  when every gate is clean and authority is explicit. Never use an admin
  bypass for another author's PR.

Chat defaults to `review --no-post`. Posting, approval, and merge are external
writes and require explicit user intent or standing project authority.

## Required context

1. Run the Agentic OS route-read loop and load the exact project profile.
2. Read durable memory as an index, then verify drift-prone facts against live
   GitHub and tracker truth.
3. Load every effective `dev_standards`, `qa_gates`, and `gitflow_topology`
   Markdown in root -> domain -> project -> invocation order.
4. Create or reuse one canonical work-item packet, keyed by tracker ticket
   when available and otherwise by PR number.

## Evidence rules

- Read PR metadata, diff, changed files, checks, reviews, comments, linked
  tracker acceptance, and required target branches from remote provider truth.
- Never treat the user's current checkout as PR evidence. A read-only cache of
  exact remote refs is allowed, but do not run local tests or application
  commands for another author's PR.
- Select only relevant specialist lanes from
  `../pull-request/references/review-lanes.md`. Each lane returns cards matching
  `../pull-request/references/finding-schema.md`.
- Every inline finding must anchor to a changed diff line. Put risks outside
  the diff in the overall review message.
- Suppress medium/low findings unless the operator lowers the severity floor.
  Do not manufacture nits to fill a clean review.

## Workflow

1. Snapshot live source, PR, checks, review threads, tracker acceptance, and
   project policy.
2. Classify ownership and implementation provenance. If the PR is operator- or
   agent-authored, review may continue, but any merge routes to
   `$auto-dev-finalize` for independent-model review.
3. Review changed behavior and enough surrounding remote code to validate
   callers, contracts, migrations, security/tenant boundaries, failure paths,
   tests, documentation, and observability.
4. Resolve the full GitFlow target family. A missing required target is a high
   finding until opened or explicitly waived.
5. Deduplicate and verify findings, then choose `comment`, `approve`, or
   `request changes`.
6. If `--post`, write through GitHub and read back the posted review.
7. In `review+merge`, require no blocking findings, green required checks, no
   unresolved actionable review thread, satisfied approvals, complete target
   coverage, no `--no-merge`, and explicit or standing project authority.
8. Record privacy-safe engineering-health observations when enabled. Missing
   reporting infrastructure never changes the review verdict.

## Merge boundary

`pr-review` owns only the other-author lane. `$auto-dev-finalize` owns the
operator/agent-authored lane. The implementation workflow never self-reviews
or self-merges.

- GPT-authored work requires FABLE review before merge.
- FABLE-authored work requires GPT review before merge.
- Human-authored work may use this AI review as the independent review.
- Missing agent provenance holds at ready for merge until a human attestation
  or valid provenance receipt exists.

Reviewer unavailability is a hold, not permission for same-model review.

## Receipts

Store the source snapshot, review provenance, target topology, raw and rendered
review, findings ledger, provider write/readback ledger, engineering-health
projection, merge decision, and summary under `artifacts/pr-review/`. Keep raw
logs and private paths local; external comments receive only scrubbed content.

Use the retained formatting and evidence references:

- `../pull-request/references/finding-schema.md`
- `../pull-request/references/review-lanes.md`
- `../pull-request/references/comment-markdown.md`
- `../pull-request/references/memory-integration.md`
- `../pull-request/references/team-health-hook.md`
- `../pull-request/references/subagents.md`
