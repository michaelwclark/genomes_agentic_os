# Spec

Add a conservative automation maturity model and file-first reconfiguration commands.

## Commands

```bash
agentic-os automation check <domain> <lane> <automation> --root ~/agentic_os
agentic-os automation attach <domain> <lane> <automation> --project <project> --root ~/agentic_os
agentic-os automation set-maturity <domain> <lane> <automation> <level> --root ~/agentic_os
```

## Acceptance

- New automations begin at `observe`.
- Maturity levels are `observe`, `prepare`, `propose`, `execute_approved`, and `execute_guarded`.
- Higher-risk maturity promotions are blocked until the automation contract has trigger, idempotency, permissions, approval, and output evidence.
- Reconfiguration writes to local markdown files and appends domain decisions.
- Project attachment updates project `status.md`, project `source-map.md`, and the automation record.
