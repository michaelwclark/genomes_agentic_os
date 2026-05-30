# Plan

1. Define the evidence contract.
   - Identify the installed OS files the analyzer may read.
   - Mark private or untrusted evidence sources.
   - Define source reference formatting so proposals can be audited later.

2. Add schemas and templates.
   - Add `self-improvement-review.yml`.
   - Add `self-improvement-proposal.yml`.
   - Add `self-improvement.yml` control-plane config.
   - Add schema validation for proposal and control-plane files.

3. Implement the dry-run analyzer.
   - Read bounded evidence windows from memory, run logs, events, doctor output,
     and registries.
   - Cluster repeated friction and missed automation opportunities.
   - Score proposals with frequency, severity, reuse, confidence, blast radius,
     and staleness.
   - Print a review without writing files.

4. Implement guarded apply mode.
   - Write proposal records only.
   - Redact secret-shaped values before writing.
   - Merge or suppress duplicates inside a cooldown window.
   - Emit an event-graph record for written proposals when event graph is
     initialized.

5. Add promotion paths.
   - Promote approved proposals to draft feature folders.
   - Promote approved proposals to draft skill folders.
   - Promote approved proposals to command prompt drafts.
   - Promote approved proposals to reference-update patch plans.

6. Wire runtime scheduling.
   - Add a disabled-by-default schedule target.
   - Let `runtime supervise` execute the analyzer as an isolated step when
     enabled.
   - Keep dry-run as the default scheduler posture.

7. Add harness knowledge.
   - Add `os-self-improvement.md`.
   - Add `toolsmith-reviewer/SKILL.md`.
   - Update docs with the operator workflow and safety model.

8. Verify.
   - Add unit tests for scoring, redaction, dedupe, and cooldown.
   - Add CLI tests for run/list/show/promote.
   - Run temp-root smoke through runtime init, analyzer dry-run, proposal apply,
     promotion, and validate.
   - Run holdout QA with noisy, stale, duplicate, and secret-bearing evidence.
