# State operations

| Operation | Command/API | Rule |
|---|---|---|
| Create portfolio | `agentic-os develop start ... --apply` | Idempotent when a caller supplies the same run id. |
| Read portfolio | `agentic-os develop status <run-dir>` | Read-only; returns portfolio and task states. |
| Advance task | `agentic-os develop stage <state.json> --stage ...` | Named stage only; every typed receipt is preflighted before the first transition. Direct `transition` fails closed. |
| Read Auto-Dev projection | `agentic-os auto-dev status <work-item>` | Reads the cross-workflow projection; canonical delivery state remains here. |
| Record failure | `agentic-os develop fail <state.json> ...` | Classifies retryability and enforces attempt budget. |
| Recover task | `agentic-os develop recover <state.json> ...` | Only allowed when the stored failure is recoverable. |
| Renew lease | `agentic-os develop heartbeat <state.json> ...` | Extends ownership without changing lifecycle state. |
| Delete/archive | cleanup workflow | Never delete active or unmerged work; archive compact receipts after retention. |
