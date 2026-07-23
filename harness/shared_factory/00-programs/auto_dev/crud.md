# Auto-Dev Lifecycle

- **Create:** use `/auto-dev`, `/auto-dev-detective`, or
  `/auto-dev-create-artifacts`; each creates one idempotent run packet.
- **Read:** use the workflow's status/resolve/explain command and compact receipt.
- **Update:** resume the same run id after new evidence, provider access, repair,
  or approval. Append events; never rewrite history.
- **Complete:** verify terminal state, artifact/provider readback, unresolved
  gaps, and handoff/cleanup.
- **Archive:** retain compact request/policy/decision/result receipts, then apply
  routed raw-evidence and worktree retention.
