# QA Lead Test Plan: Overnight Runtime Stabilization 2026-07-03

## Scope

This QA plan covers the overnight Agentic OS runtime stabilization work shipped
to `genomes_agentic_os` through `2637ec7`.

Included implementation items:

- Lifecycle Doctor And Validation: done.
- GAP-164 automation_control_tick priority dispatch: done.
- GAP-113 stale `self-improvement.yml.new`: done by verification.
- GAP-112 missing `update-grant.json`: done by license activation, update
  registration, and backup dry-run verification.
- GAP-142 committed `RUN_STATE.json`: done by removing the tracked file and
  ignoring future runtime state snapshots.
- GAP-056 docs-upkeep source-template fallback: done.
- Always-On Runtime spec: still in progress because it is broader than this
  stabilization pass.
- GAP-172 run-queue pruning: still in progress because queue write batching was
  fixed, but live TTL/prune cleanup was not applied.
- Lifecycle Closeout Gate: intentionally reopened; the earlier note was a
  corrected row-targeting mistake.

## Risk Map

- User workflow risk: medium. Runtime commands now recover better from stale
  schedules and queue backlog, but the live queue still contains historical
  backlog until a guarded prune is run.
- Backend/API contract risk: low. Changes are local CLI/runtime behavior and
  file-backed state transitions, covered by existing CLI tests.
- Frontend state and component risk: not_applicable - no frontend code changed.
- Permission/security risk: medium. `update register` generated local SSH key
  material under the installed OS; private keys are excluded by backup policy and
  were not printed.
- Data, tenant, migration, and config risk: medium. The source repo no longer
  tracks `RUN_STATE.json`; installed runtime state remains local.
- Integration and side-effect risk: medium. Backup/update now have a registered
  grant and dry-run works. Remote backup apply was not executed.
- Regression risk: medium. Docs-upkeep fallback and queue batching both touch
  runtime paths that can behave differently in installed vs source checkouts.
- Rollout and post-release risk: medium. Existing live runtime doctor findings
  should be expected until the stale queue and due schedules are handled.

## Preconditions

- Work ran from `/Users/genome/projects/genomes_agentic_os` on `main`.
- Genome's Notion was verified through the report ancestor path before writes.
- Local installed OS root was `/Users/genome/agentic_os`.
- Repo virtualenv was used for tests: `.venv/bin/python`.
- No production LOS shell access or Kubernetes access was used.
- No remote backup apply was run.

## Automated Checks

- run: `.venv/bin/python -m pytest tests/test_cli_scaffold.py tests/test_runtime_supervise.py tests/test_validation_strictness.py -q`
  Result: `153 passed` before the second pass.
- run: `.venv/bin/python -m pytest tests/test_documentation_upkeep.py tests/test_cli_scaffold.py tests/test_runtime_supervise.py tests/test_validation_strictness.py -q`
  Result: `157 passed`.
- run: `.venv/bin/python -m pytest tests/test_documentation_upkeep.py tests/test_cli_scaffold.py::test_schedule_run_due_batches_queue_load_for_multiple_due_schedules tests/test_runtime_supervise.py::test_runtime_dispatches_latest_priority_ref_and_skips_older_duplicates -q`
  Result: `6 passed`.
- run: `agentic-os docs upkeep --root /Users/genome/agentic_os --write-receipt`
  Result: `ok: true`, 2 stale entries, 0 missing sources, receipt written.
- run: `agentic-os backup run --root /Users/genome/agentic_os --dry-run`
  Result: planned backup successfully, local log written, no remote apply.
- run: `git check-ignore -v RUN_STATE.json`
  Result: `.gitignore` owns the ignore rule.
- run: `git ls-files RUN_STATE.json`
  Result: no tracked source file remains.
- run: Notion status readback through direct API.
  Result: six worked high-impact rows are `done`; two broader items remain
  `in-progress`; `Lifecycle Closeout Gate` is `inbox`.

## Manual Test Script

1. Open the overnight runtime stabilization report in Notion.
   Expected: it lists the first pass and second-pass completion, including the
   correction for `Lifecycle Closeout Gate`.
2. Open each worked OS Work Intake row.
   Expected: each row has a plain-English "what we built" or verification note.
3. Check the repo on `main`.
   Expected: `git status --short --branch` reports clean and `HEAD` is
   `2637ec7` or newer.
4. Check runtime update grant state.
   Expected: customer identity has `license.status: active`,
   `update_grant.status: registered`, and the grant file exists.
5. Run docs upkeep on a fresh installed root or fixture.
   Expected: if the live config is missing, the installed template path is used.
6. Run a runtime schedule test or dry-run on a non-production fixture.
   Expected: due schedules batch queue writes, and priority schedules dispatch
   the newest queued ref.

## Regression Matrix

| Area | Regression Target | Expected Result | Status |
| --- | --- | --- | --- |
| Runtime schedules | Stale interval catch-up | Next due time advances into the future | run |
| Runtime supervisor | Priority dispatch refs | Newest queued priority item is selected | run |
| Run queue performance | Multiple due schedules | Queue loads once per schedule pass | run |
| Validation | Generated work item drift | Warnings instead of hard failures | run |
| Docs upkeep | Missing live config | Installed template fallback succeeds | run |
| Source hygiene | `RUN_STATE.json` | Not tracked and ignored | run |
| Update/backup gate | Missing update grant | Registered grant unblocks backup dry-run | run |
| Live queue cleanup | Historical queue entries | TTL/prune still required | planned |
| Closeout gate | Lifecycle closeout enforcement | Separate implementation still required | planned |

## Evidence

- Source commits: `39adb08`, `afd531a`, `2637ec7`.
- Current pushed head during QA: `2637ec7`.
- Test receipt: `157 passed in 62.41s`.
- Docs-upkeep receipt:
  `/Users/genome/agentic_os/harness/shared_factory/06-runs-and-logs/documentation-upkeep/runs/20260703-second-pass/`.
- Backup dry-run log:
  `/Users/genome/agentic_os/harness/logs/backups/backup-20260703094247.yml`.
- Notion report: `Overnight high-impact runtime stabilization report - 2026-07-03`.

## Pass/Fail Criteria

Pass if:

- The repo is clean on `main` and all commits are pushed.
- The affected test suite passes.
- Runtime state files are not tracked.
- Documentation upkeep runs from the installed OS.
- Update grant exists and backup dry-run plans successfully.
- Every worked Notion row has a plain-English build/verification note.

Fail if:

- `RUN_STATE.json` reappears in `git ls-files`.
- Docs upkeep requires source checkout layout when installed templates exist.
- Priority dispatch cannot find `automation_control_tick`.
- Backup dry-run fails because the update grant is missing.
- Any worked row lacks Notion documentation.

## Recommended Execution Handoff

qa-analysis is not required. This is Agentic OS runtime/source work, not an LOS
Jira browser workflow. If a future LOS Django item from the same queue is picked
up, use the LOS-specific QA workflow for that item.

## Blockers and Follow-ups

- GAP-172 remains in progress: implement guarded run-queue TTL/prune cleanup and
  run it against the live queue.
- Always-On Runtime remains in progress: this pass implemented several runtime
  primitives, but the full always-on runtime surface is broader.
- Lifecycle Closeout Gate remains inbox: build the closeout gate separately.
- Runtime doctor will still report historical due/backlog findings until the
  live queue cleanup and schedule tick are handled.
- Remote backup apply remains unrun by design; only dry-run was validated.

## Post-release Smoke

- Run the affected pytest suite after any additional runtime queue cleanup.
- Run `agentic-os runtime doctor --root /Users/genome/agentic_os` and compare
  findings before/after the queue prune.
- Run `agentic-os docs upkeep --root /Users/genome/agentic_os --write-receipt`
  after any docs routing changes.
- Run `agentic-os backup run --root /Users/genome/agentic_os --dry-run` after
  any update-grant or backup-policy changes.
- Re-query OS Work Intake high-impact rows and verify statuses match the actual
  shipped state.
