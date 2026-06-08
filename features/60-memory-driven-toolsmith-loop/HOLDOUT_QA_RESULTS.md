# Holdout QA Results

Status: PASS

Date: 2026-06-08

## Commands

- `.venv/bin/python -m pytest -q tests/test_cli_scaffold.py -k 'self_improvement'`
  - Result: `8 passed, 86 deselected`
- `.venv/bin/python -m compileall -q src/genomes_agentic_os && .venv/bin/python -m pytest -q`
  - Result: `97 passed in 14.64s`
- `git diff --check`
  - Result: passed
- `rg -n "def approve_self_improvement|def promote_self_improvement|def run_self_improvement|weekly_self_improvement|self_improvement_review" src/genomes_agentic_os/self_improvement.py src/genomes_agentic_os/runtime_ops.py tests/test_cli_scaffold.py features/60-memory-driven-toolsmith-loop/HOLDOUT_QA_RESULTS.md`
  - Result: one `run`, one `approve`, one `promote`, and one
    `self_improvement_review` schedule id

## Temp-Root Smoke

Created a fresh temporary installed root, seeded repeated failure/manual evidence
with a token-shaped value, and verified the final path in
`/tmp/aos-self-improvement-final.kFiK3b`:

- `self-improvement run --apply` wrote run/proposal records only under
  `harness/shared_factory/06-runs-and-logs/self-improvement/`.
- Proposal output did not include the raw token-shaped value.
- `approve --target feature-spec` wrote a content-bound approval record.
- `promote --target feature-spec` wrote draft `feature.yml`, `SPEC.md`,
  `PLAN.md`, and `NEXT.md` under the configured drafts directory.
- `runtime init` included a disabled `self_improvement_review` schedule target.
- Enabling that schedule, running `schedule run-due --apply`, and dispatching
  with `runtime run-next --apply` completed successfully.

## Covered Risks

- Dry-run writes nothing.
- Apply writes proposal/run records only.
- Dedupe keeps repeated apply from creating duplicate active proposals.
- Rejected duplicate proposals are suppressed during cooldown.
- Approval binds proposal content, validation, target, and control-plane hashes.
- Promotion rejects mutated approved proposal content.
- Unsafe output paths are rejected without creating escape files.
- Scheduler integration is disabled by default and dispatchable when explicitly
  enabled.
