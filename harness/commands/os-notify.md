# OS Notify

Canonical slash command: `/notify`

Use this command only when the current scoped work has produced a bounded,
operator-actionable signal. It sends a local macOS notification through the
single Agentic OS delivery seam; it does not send Slack, email, tracker, or
customer-facing messages.

## When To Use It

- `info`: a meaningful state change that deserves awareness but no prompt action.
- `warning`: attention is needed soon, such as a high-priority ticket or a
  watcher finding that should be reviewed.
- `error`: a build, test, automation, or integration failed and needs action.
- `critical`: immediate attention is warranted for a severe or repeatedly
  escalating condition.

Do not notify for ordinary progress, normal success, unchanged repeat failures,
or a condition already clear in the active chat. The policy may suppress a
notice during quiet hours or when its cooldown/hourly cap is reached; do not
bypass those protections.

## Invocation

Load the final routed `TOOLS.md`, then use the notifier at the installed root:

```bash
<root>/harness/bin/agentic-os-notify \
  --source <area.component> \
  --level <info|warning|error|critical> \
  --title "<short actionable title>" \
  --message "<what happened and what needs attention>" \
  --dedupe-key "<stable-condition-id>"
```

Use `--dry-run` while wiring a new source. Use `--url <approved-url>` only when
the click destination is safe and useful. The retained delivery and suppression
history is at `harness/shared_factory/06-runs-and-logs/alerts/alerts.jsonl`;
inspect it with `--history` and retain no parallel history.

## New Source Recipe

Before a watcher or automation sends a notification, add an inherited source
entry to `harness/registries/alerts.yml`:

```yaml
sources:
  automation.example_check:
    enabled: true
    min_level: warning
    cooldown_seconds: 900
    max_deliveries_per_hour: 3
```

Keep the source id stable. The entry inherits global quiet hours, the 48-hour
history retention rule, severity defaults, and critical-rate-limit bypass unless
the local policy deliberately overrides them.

## Guardrails

- Do not modify global quiet hours, retention, or rate limits merely to force a
  notice through.
- Do not send a notification before a real failure or priority condition is
  evidenced in the current task's receipt, source, or run artifact.
- Do not put secrets, customer data, private filesystem paths, or verbose logs
  into the title or message.
