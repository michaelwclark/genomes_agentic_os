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
