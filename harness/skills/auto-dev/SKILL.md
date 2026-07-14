---
name: auto-dev
description: Run a Jira or Linear tracker item through project-aware SDLC orchestration, state-machine receipts, mandatory finishing review, PR/CI/Copilot loops, and safe merge or merge-blocked closeout. LOS Work Plan rows are a queue adapter.
---

# Auto Dev

Auto Dev is the Agentic OS dark-factory SDLC runner. It starts from a tracker
item, resolves the routed project `project.yml dev_factory` block, creates or
resumes a local state-machine run, delegates implementation to the project
executor, requires receipt-backed quality gates, and stops only at
`ready_for_merge`, `merged`, `blocked`, or `abandoned`.

The LOS Work Plan queue is an adapter and compatibility trigger. It can launch a
run, but it is not the canonical state/spec/worklog source. Notion is
projection-only.

## Hard Rules

- Read the Agentic OS routed layer before acting. At the auto-dev program layer,
  load `program.md`, `components.yml`, `config/auto-dev-queue.yml`, `RULES.md`,
  and the target project `project.yml`.
- Use `project.yml dev_factory` for every project-specific behavior: tracker,
  repo path, base branch, branch template, validation commands, PR provider,
  Copilot policy, finishing-review policy, projection policy, and merge policy.
  Missing required config blocks the run; never silently default to LOS, Jira,
  Notion, `develop`, or `make t`.
- Edit this harness source only. The `.agents/skills/auto-dev/` and
  `$HOME/.codex/skills/auto-dev/` copies are generated; refresh them with:

```bash
harness/bin/register-codex-skills --root /Users/genome/agentic_os --user-scope
```

- Never use `--no-verify`, force-push, destructive git, or auto-merge unless
  `dev_factory.merge.policy` explicitly allows it. The default is `never_auto`.
- Every tracker/GitHub/Slack/email writeback must pass the scrubber first. A
  finding blocks the write.
- `awaiting_human_review` is paused and non-error. Release the local claim and
  do not write it to the tracker as `blocked`.

## Local State

The canonical artifact root is:

```text
<work-item>/artifacts/auto-dev/
  state.json
  step-ledger.jsonl
  state-decision.json
  tracker/source-snapshot.json
  tracker/writeback-ledger.jsonl
  context/context-load.json
  context/project-profile-snapshot.yml
  plan/implementation-plan.md
  plan/task-checklist.yml
  quality/quality-gate-ledger.jsonl
  pr/pr-state.json
  ci/ci-watch-state.json
  copilot/copilot-watch-state.json
  finishing-touches/<run-id>-pre_pr/
    review-request.json
    validation-plan.json
    review-ledger.jsonl
    reviewer-prompt.md
    reviewer-response.md
    model-receipt.md
    readiness-decision.json
  finishing-touches/<run-id>-post_pr/
    readiness-decision.json
  projection/
  merge/merge-state.json
```

`state.json` is authoritative and references sub-artifacts; it does not duplicate
their contents. `step-ledger.jsonl` is append-only. State writes are atomic.

Operate state with:

```bash
python3 harness/skills/auto-dev/scripts/auto_dev_state.py init --run-dir <work-item>/artifacts/auto-dev ...
python3 harness/skills/auto-dev/scripts/auto_dev_state.py claim --run-dir <dir> --owner-run-id <id> --distributed-token <tracker-claim> --receipt <receipt>
python3 harness/skills/auto-dev/scripts/auto_dev_state.py transition --run-dir <dir> --to <state> --receipt <receipt> --idempotency-key <key>
python3 harness/skills/auto-dev/scripts/auto_dev_state.py recover --run-dir <dir>
python3 harness/skills/auto-dev/scripts/auto_dev_state.py render --run-dir <dir>
python3 harness/skills/auto-dev/scripts/auto_dev_state.py release --run-dir <dir> --reason <reason>
python3 harness/skills/auto-dev/scripts/auto_dev_state.py decide --run-dir <dir>
```

Legal forward path:

```text
discovered -> claimed -> context_loaded -> planned -> worktree_ready
-> implementing -> local_validation -> finishing_review(pre_pr)
-> pr_open -> ci_watch -> copilot_watch -> finishing_review(post_pr)
-> ready_for_merge -> merged
```

`awaiting_human_review` is reachable from either finishing-review checkpoint.
`blocked` and `abandoned` are terminal stop states available from any
non-terminal state with a receipt.

## Tracker Contract

Supported modes:

- `jira`: Jira owns spec, AC, workflow, writeback, PR state, merge state, and
  closeout.
- `linear`: Linear owns spec, AC, workflow, writeback, PR state, merge state,
  and closeout.
- `hybrid`: Jira owns spec/workflow/company writeback; Linear is a personal
  mirror only. Do not mention the Linear personal board in Jira/GitHub text and
  never derive Jira state from Linear.

The claim token is tracker-side: set assignee to the configured Auto Dev owner,
add the configured claim label, transition to the configured in-progress state,
then re-read. If assignee or label do not match, block as `duplicate_claim`.
The local `state.json.claim` heartbeat prevents same-host duplicates only.

Use the fixture-backed adapters in `scripts/tracker/` for contract tests. Live
provider writes must go through the configured Jira/Linear tool route and the
scrubber.

## Project Profile

Load `project.yml dev_factory` before claim. Required sections:

- `enabled`
- `queue_source`
- `tracker`
- `repo`
- `validation`
- `finishing_review`
- `pull_request`
- `copilot`
- `merge`
- `projection`

If `dev_factory.tracker.ac_source` is missing or unparseable, block with
`config_missing` or `acceptance_criteria_missing`. Do not infer AC from Notion.

LOS remains on the Notion queue adapter until Genome approves Phase-7 cutover.
For LOS, keep `dev_factory.queue_source.mode: notion_compat` and
`tracker_queue_enabled: false`.

## Finishing Review

The finishing gate is mandatory and runs twice:

- `pre_pr`: after `local_validation`, before `pr_open`. Target decision:
  `ready_pre_pr`.
- `post_pr`: after `ci_watch` and `copilot_watch`. Target decision:
  `ready_post_pr_checks`.

Use the existing engine; do not alter its decision logic:

```bash
python3 harness/skills/finishing-touches-review/scripts/finishing_touches_review_helper.py decide --run-dir <review-run-dir>
```

The canonical Anthropic-family reviewer transport is the installed Claude CLI,
using its native login. Never call the Anthropic API or SDK for this gate. Remove
API credentials from the child process so an exported key cannot silently
override CLI-native authentication:

1. Transition to `finishing_review`.
2. Generate the prompt:

```bash
python3 harness/skills/auto-dev/scripts/auto_dev_state.py prepare-review \
  --run-dir <dir> --mode pre_pr \
  --reviewer-transport claude_cli \
  --review-unavailable-policy continue_with_receipt
```

3. Run the deterministic Claude CLI wrapper:

```bash
python3 harness/skills/auto-dev/scripts/auto_dev_state.py run-review \
  --run-dir <dir> \
  --review-run-dir <dir>/finishing-touches/<run-id>-pre_pr \
  --reviewer-model opus \
  --review-unavailable-policy continue_with_receipt
```

`prepare-review` records the canonical reviewed repository, preferring the
state-machine worktree over the base repository, plus the expected head SHA.
`run-review` rechecks both against current state and `git rev-parse HEAD` before
Claude starts. It executes the equivalent of
`env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN claude -p --model opus
--safe-mode --permission-mode dontAsk` from that verified worktree, with only
`Read`, `Grep`, `Glob`, and read-only `git diff/show/status/log` Bash commands.
It passes `reviewer-prompt.md` on stdin and writes only stdout to
`reviewer-response.md`. It never persists raw stderr. On success it ingests the
response automatically.

4. If a response was obtained outside the wrapper, ingest it explicitly:

```bash
python3 harness/skills/auto-dev/scripts/auto_dev_state.py ingest-review --run-dir <dir> --review-run-dir <dir>/finishing-touches/<run-id>-pre_pr
```

5. If Claude CLI is missing, unauthenticated, out of CLI-accessible capacity,
times out, or otherwise fails, `run-review` records the sanitized failure
instead of trying an Anthropic API key. For a manually detected failure, use:

```bash
python3 harness/skills/auto-dev/scripts/auto_dev_state.py record-review-unavailable \
  --run-dir <dir> \
  --review-run-dir <dir>/finishing-touches/<run-id>-pre_pr \
  --failure-code cli_auth_failed \
  --failure-summary "Claude CLI native authentication unavailable" \
  --review-unavailable-policy continue_with_receipt
```

`record-review-unavailable` writes a sanitized `model-receipt.md`, updates the
validation plan, invokes the deterministic finishing helper, and resumes when
the helper returns `ready_pre_pr` or `ready_post_pr_checks`. Claude CLI transport
failure is noted but does not block delivery by default. A project may set
`review_unavailable_policy: block` for security- or compliance-sensitive work.
Actual reviewer findings, failed validation, CI failures, and product decisions
remain blocking; the unavailable path refuses to replace an opened finding.
Non-empty Claude output that is malformed is also not reviewer unavailability:
keep `reviewer-response.md`, remain in `awaiting_human_review`, and write
`review-output-error.json` for inspection or explicit re-ingestion.

`ingest-review` validates the JSON findings array and `VERDICT:` line, appends
findings to `review-ledger.jsonl`, writes `model-receipt.md`, runs the finishing
helper's `decide`, and resumes the state machine.

Unattended reviewer execution remains allowed only behind `reviewer_mode: auto`
after a host proves unattended Claude CLI invocation works.

## Implementation Path

1. Resolve tracker and project config from routed context.
2. Create or reuse the work item and `artifacts/auto-dev/state.json`.
3. Claim tracker-side and local heartbeat lock.
4. Load project context and write context receipts.
5. Plan and implement through `quiet-workon-orchestrate`, using the resolved
   project config.
6. Run local validation or write an explicit downgrade receipt.
7. Run pre-PR finishing review.
8. Create or reuse the PR and sanitized tracker writeback.
9. Enter the PR watch-and-repair loop. Starting a watcher is not a
   completion receipt; failed checks must be inspected, fixed, pushed, and
   watched again.
10. Resolve Copilot loops with bounded rounds and receipts until no unresolved
    actionable Copilot/review threads remain.
11. Run post-PR finishing review.
12. Stop at `ready_for_merge` unless project merge policy and explicit approval
    allow merge.
13. Project concise state to Notion as best-effort write-only operator view.

## LOS PR And Code Documentation Style

For LOS Django PRs, use the current senior-engineer PR shape observed in recent
merged `dennijo` PRs:

```markdown
## Description of the Feature or Problem

Explain the customer/product failure, affected tenant/app when known, and why
the current behavior is wrong.

## Description of the Change

Explain the code path changed, the invariant being enforced, and why the fix is
at this layer rather than a narrower symptom patch.

### Associated Jira(s)

- [FLYWL-1234](https://venturesgo.atlassian.net/browse/FLYWL-1234)

### Checklist

- [x] I have tested this change locally
- [x] I have added or modified applicable unit tests
- [ ] New frontend files follow `Domain.concern.extension` where applicable

## Test Evidence

List exact local commands when run, or state that GitHub CI is the final
readiness signal when local validation is intentionally skipped or blocked.

## Risk

Call out scope, guardrails, data/migration impact, and known follow-ups.
```

Use GitHub PR links in team-visible text as
`[thesummitgrp/los-app-los-django#12345](https://github.com/thesummitgrp/los-app-los-django/pull/12345)`.

For bugfix code, include explanatory inline comments at the guard, fallback, or
data-repair seam that explain:

- what invalid state or historical production path is being handled;
- why the fallback is safe for the affected workflow;
- how the guard preserves existing behavior for unaffected tenants/products.

Do not add comments that merely restate obvious assignments, but prefer a
specific what/why/how comment when the fix encodes production history, tenant
configuration behavior, workflow invariants, or a non-obvious data edge case.

## PR Watch And Repair Loop

`ci_watch` and `copilot_watch` are active work states. Do not close an
interactive or queued `$auto-dev` run merely because a PR was opened or a quiet
watcher was started.

CI loop:

1. Start `/watch-pr-quiet` for the PR and write state under
   `artifacts/auto-dev/ci/` or the project-configured PR-watch folder.
2. When the watcher reaches a terminal result, save failed job logs under the
   work item's artifacts and summarize only the failing check names, job ids,
   and root cause in chat or tracker writeback.
3. If a failed job has no test failure or code traceback, classify it as
   infrastructure. Rerun once when the project policy allows it; if the same
   infrastructure class repeats, block with the log receipt and owner action.
4. If a failed job identifies code or test failures, make the narrowest fix,
   run the smallest local validation available or record an explicit local
   blocker, commit, push, and restart the PR watcher for the new head SHA.
5. Continue until required checks pass, a configured loop limit is hit, or a
   product/security/architecture decision is needed.

Copilot/review loop:

1. After every push and after green CI, query unresolved GitHub review threads,
   including Copilot threads.
2. Classify the thread set with:

```bash
python3 harness/skills/auto-dev/scripts/copilot_loop.py --input <threads.json> --output <receipt.json>
```

3. For `fix_required`, patch, validate, commit, push, resolve the addressed
   thread, and rerun the CI loop.
4. For `reply_and_resolve`, reply with sanitized team-visible context, resolve
   the thread, and record the receipt.
5. For `blocked_product_decision` or `blocked_loop_limit`, transition to
   `blocked` with the exact receipt and next action.

Post-PR finishing review may run only after `ci_green=passed` and
`copilot_clean=passed` or explicit project-policy skip receipts exist. Ready
for Merge requires the post-PR finishing decision in addition to those gates.

## Verification

Before declaring a run or implementation phase done, run the relevant helpers:

```bash
python3 harness/skills/auto-dev/scripts/auto_dev_state.py fixture-test --fixtures harness/skills/auto-dev/fixtures
python3 harness/skills/finishing-touches-review/scripts/finishing_touches_review_helper.py fixture-test --fixtures harness/skills/finishing-touches-review/fixtures
python3 -m unittest harness/skills/auto-dev/tests/test_auto_dev_v2.py
```

For external write text:

```bash
python3 harness/skills/auto-dev/scripts/auto_dev_state.py scrub-external-output --input <draft> --output <scrubbed>
```

Exit code `2` means the write is blocked.

For Copilot loop receipts:

```bash
python3 harness/skills/auto-dev/scripts/copilot_loop.py --input harness/skills/auto-dev/fixtures/copilot/threads.json
```

`blocked_product_decision` and `blocked_loop_limit` stop the run with a blocker
receipt; actionable findings return to implementation, and false positives get
a reply-and-resolve receipt.

## `auto-dev <project> <NNN>` Resolver

When the user says `auto-dev <project> <NNN>` (e.g. `auto-dev losmon 002`),
**run the resolver first** and follow its output before starting any auto-dev
session.

```bash
agentic-os-auto-dev-resolve <project> <NNN> [--allow-specified] [--root DIR]
```

The resolver:

1. Finds the project directory across all domains (`los`, `clarks_consulting`,
   `personal`, `harness/shared_factory`).
2. Locates the packet at `work-items/*/<NNN>_*/` and reads its SPEC.md `state:`.
3. Applies the **stage gate** from `harness/rules/work-lifecycle-standard.md`:
   - `captured` / `triaged` → exit 2, prints grooming route
     (`spec-intake` / `aos-product-orchestrator`).
   - `specified` without `--allow-specified` → exit 2, prints:
     "Add `--allow-specified` or promote to `ready`."
   - `ready` / `building` / `validating` / `blocked` → proceeds.
   - `finished` / `documented` / `archived` → exit 2, item is closed.
4. Runs preflight checks: `dev_factory` present, tracker id found, repo path
   exists. Prints PASS/FAIL + remedy for each.
5. On all-pass: writes `artifacts/auto-dev/run-prompt.md` and prints the
   ready-to-paste run prompt.

**Follow the resolver output:** if it blocks (exit 2), do not start auto-dev —
route the item as directed. If it passes, use the printed prompt to invoke the
harness session.

## Closeout

Every phase must leave a local receipt under the work item: files changed,
verification commands and outcomes, acceptance criteria covered, 50/50 choices,
deferrals, and blockers. Do not declare completion with failing checks.
