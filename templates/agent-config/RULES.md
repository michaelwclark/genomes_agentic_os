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
- Artifact-producing workflows—including nested output from intake, Spec
  Engine, Detective, Auto-Dev stages, review, release, reports, closeout,
  program/workflow creation, and automations—must follow
  `harness/rules/auto-dev-artifact-producers.md`: resolve `artifact-config`,
  render/validate locally, verify target, apply only with approval, and read
  back every external write.
- Development/review workflows must load the effective development, QA, and
  gitflow Markdown policy planes and record their source list/fingerprint.
- Environment-scoped investigation must identify the deployed version before
  choosing code. Read-only investigation never authorizes mutation. When VPN,
  environment, authentication, or a provider is unavailable, pause one
  receipt-backed run and resume it after fresh availability evidence; do not
  create repeated failure attempts.

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

## Managed Execution Rules

- When Execution Fabric is enabled, admit managed workflow and automation work
  through its configured named queues. Folder counts, detached launches, and
  direct vendor queue writes are not concurrency controls.
- Route queue selection, workers, retries, dead letters, effect delivery,
  alarms, healing, and failover to
  `harness/shared_factory/00-programs/execution_fabric/`; do not copy those
  rules into each workflow.
- Preserve admission, assignment, attempt, effect, and terminal run receipts.
  A trigger, process id, or health endpoint alone does not prove execution.
