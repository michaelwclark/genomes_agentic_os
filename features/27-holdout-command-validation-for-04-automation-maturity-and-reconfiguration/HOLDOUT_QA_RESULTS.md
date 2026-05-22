# Holdout QA Results

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.24s
```

## Automation Maturity Smoke

Commands:

```bash
TMP_ROOT=$(mktemp -d /tmp/agentic-os-automation-holdout-XXXXXX)
ROOT="$TMP_ROOT/os"
uv run agentic-os init --target "$ROOT"
uv run agentic-os project create support support_intake --root "$ROOT" \
  --repo /tmp/support-intake --notion https://www.notion.so/support \
  --jira SUPPORT --lane ready
uv run agentic-os automation create support support thread_intake --root "$ROOT"
uv run agentic-os automation check support support thread_intake --root "$ROOT"
uv run agentic-os automation set-maturity support support thread_intake propose --root "$ROOT"
uv run agentic-os automation set-maturity support support thread_intake prepare --root "$ROOT"
uv run agentic-os automation attach support support thread_intake --project support_intake --root "$ROOT"
uv run agentic-os validate --root "$ROOT"
grep -RIn "thread_intake\|prepare\|support_intake" "$ROOT/support" "$ROOT/00-control-plane"
```

Initial check result:

```text
automation: .../support/04-automations/support/thread_intake
level: observe
findings:
- severity: fix-soon
  message: 'section needs content: Outputs'
- severity: blocker
  message: 'missing required evidence: trigger source'
- severity: blocker
  message: 'missing required evidence: trigger frequency'
- severity: blocker
  message: 'missing required evidence: idempotency key'
- severity: blocker
  message: 'missing required evidence: duplicate handling'
- severity: blocker
  message: 'missing required evidence: read permissions'
- severity: blocker
  message: 'missing required evidence: write permissions'
- severity: blocker
  message: 'missing required evidence: approval gates'
- severity: blocker
  message: 'missing required evidence: outputs'
```

Unsafe promotion guard:

```text
exit_code=2
error: cannot advance automation to propose; unresolved blocker: missing required evidence: trigger source
```

Safe promotion:

```text
automation: .../support/04-automations/support/thread_intake
old_level: observe
new_level: prepare
decision_log: .../support/00-control-plane/decisions.md
```

Project attachment:

```text
automation: .../support/04-automations/support/thread_intake
project: .../support/02-projects/support_intake
project_status: .../support/02-projects/support_intake/status.md
source_map: .../support/02-projects/support_intake/source-map.md
```

Validation:

```text
valid: /tmp/agentic-os-automation-holdout-L2bo2n/os
```

Evidence scan found the maturity decision, source-map automation row, and
project status automation row for `thread_intake` at level `prepare`.
