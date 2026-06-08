# Worklog

## 2026-05-30

- Created local feature folder for the memory-driven toolsmith loop.
- Added spec, plan, metadata, investigation, judgment, summary, next step, and
  local memory notes.

## 2026-05-31

- Reviewed `nousresearch/hermes-agent` at commit
  `04bb74c58eff5ac972e31bcf2fa2c7c7aaf5105b` for self-improvement mechanics.
- Added Hermes research notes covering background memory/skill review, curator
  scheduling, sidecar skill usage telemetry, per-run reports, and cron skill
  reference rewrites.
- Reframed Feature 60 as a default installed shared workflow plus
  disabled-or-dry-run automation, with proposal-only mutation in v1.
- Ran the default duel command first; it stopped before round 1 because the
  local Claude CLI writer returned `Credit balance is too low`.
- Re-ran the duel with local Codex CLI for both writer and critic, avoiding
  paid OpenRouter fallback. It passed in 3 rounds with final output at
  `.duels/2026-05-31-codex-local/final-spec.md`.

## 2026-06-03

- Folded the duel PASS artifact into `SPEC.md`.
- Updated `PLAN.md`, `HOLDOUT_QA.md`, `NEXT.md`, `JUDGMENT.md`, and `MEMORY.md`
  so implementation starts from the reviewed P1 slice: managed templates,
  schemas, default install inclusion, and no-write dry-run analysis.

## 2026-06-08

- Completed the v1 self-improvement loop through local file-backed surfaces.
- Added apply mode, proposal writes, dedupe/cooldown suppression, safe output
  path checks, per-proposal locks, content-bound approval, reject, promote, and
  draft artifact generation.
- Added a disabled `self_improvement_review` runtime schedule target and local
  script dispatch support for dry-run scheduler execution.
- Added managed-template checksum conflict handling for the self-improvement
  managed surface.
- Verified with focused self-improvement tests, full pytest, diff whitespace
  checks, and a temp-root smoke covering apply, approve, promote, and scheduler
  dispatch.
