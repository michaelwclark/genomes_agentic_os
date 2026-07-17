---
name: notification-operator
description: Send one governed local macOS notification for an operator-actionable Agentic OS condition without creating alert noise.
---

# Notification Operator

Use this skill when a task produces an operator-actionable event and a local
macOS notification is appropriate.

## Procedure

1. Confirm the condition is actionable and receipt-backed. Do not use a
   notification for routine success, normal progress, or an unchanged repeat.
2. Select severity: `info` for awareness, `warning` for timely review, `error`
   for a failed condition needing action, and `critical` for prompt attention.
3. Use the stable source id registered in `harness/registries/alerts.yml`. For
   a new recurring source, add a conservative inherited source policy before
   delivery; do not use unregistered sources as a permanent path.
4. Send one notice with a concise title, actionable message, and stable
   `--dedupe-key`. Use `--dry-run` for new wiring.
5. Respect the notifier's quiet hours, cooldown, and hourly caps. Suppression is
   an expected outcome, not a reason to retry or bypass policy.
6. Inspect `--history` when a delivery result needs explanation. The canonical
   history is local at
   `harness/shared_factory/06-runs-and-logs/alerts/alerts.jsonl` and is pruned
   after 48 hours by policy.

## Invocation

```bash
<root>/harness/bin/agentic-os-notify \
  --source <area.component> \
  --level <info|warning|error|critical> \
  --title "<short actionable title>" \
  --message "<what happened and next action>" \
  --dedupe-key "<stable-condition-id>"
```

Notifications are local macOS effects only. They never authorize external
Slack, email, tracker, customer-facing, or production actions.
