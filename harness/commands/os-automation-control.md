# OS Automation Control

Use when expensive recurring automations should run only after their source has actionable work.

## Procedure

1. Identify the source that proves work exists: Notion queue rows, a connected-source watch definition, or another source probe.
2. Configure `harness/shared_factory/00-control-plane/automation-control.yml` with one managed automation per target.
3. Keep the original expensive automation disabled or paused; let the controller
   admit the target through the selected runtime only when the probe returns
   `ready`. With Execution Fabric enabled, this means one configured named
   queue and idempotency key through `agentic-os runtime submit`, never a
   direct Valkey/BullMQ write or a detached process.
4. Run `agentic-os automation-control doctor --root <root>` before enabling a schedule.
5. Preview with `agentic-os automation-control run --root <root> --dry-run`.
6. Wire one cheap schedule to `agentic-os automation-control run --root <root> --apply`.

## Output

Return the controller config path, effective Execution Fabric policy source and
fingerprint when managed mode is selected, doctor findings, per-automation
decision, admission/queue action, and durable receipt under
`harness/shared_factory/06-runs-and-logs/automation-control/`.
