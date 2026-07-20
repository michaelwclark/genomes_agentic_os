# Rules

Record local constraints, approval gates, safety boundaries, coding rules, and operating rules for this layer.

## Precedence

- Active user instructions win.
- The final routed layer is the working context.
- The strictest safety, approval, privacy, and destructive-action rule wins across parent and child layers.

## Approval Gates

- External writes require explicit approval.
- Customer-visible output requires explicit approval.
- Production changes require explicit approval.
- Destructive actions require explicit approval.
- Secrets, billing, and legal records require explicit approval.

## Operating Rules

- Route before creating or changing artifacts.
- Preserve source links, validation evidence, and next actions.
- Do not store secrets in markdown, config files, logs, or memory.
- Artifact-producing workflows must resolve `artifact-config` before rendering
  and must validate, verify target, and read back any external write.
- Development/review workflows must load the effective development, QA, and
  gitflow Markdown policy planes and record their source list/fingerprint.
- Environment-scoped investigation must identify the deployed version before
  choosing code. Read-only investigation never authorizes mutation.

## Notification Rules

- Treat local notifications as an attention budget, not a progress stream.
- Use `info` only for a meaningful state change that merits awareness; use
  `warning` when attention is needed soon; use `error` for a failed condition
  requiring action; use `critical` only when prompt attention is warranted.
- Use a stable source id and a `--dedupe-key` for recurring state alerts. Do
  not work around quiet-hours, cooldown, or hourly-cap suppression.
- Before introducing a new watcher or automation source, add its inherited
  policy entry to `harness/registries/alerts.yml` and use the documented dry
  run. Never create a second notifier or a parallel alert-history location.
- Notifications are local macOS effects. They do not authorize Slack, email,
  tracker, customer-facing, or production actions.
