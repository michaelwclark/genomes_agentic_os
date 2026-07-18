# Harness Commands

Each file is the durable contract for one command exposed through Agentic OS
harnesses. The Python CLI or a small helper performs deterministic work; the
command document explains routing, inputs, safety gates, and output receipts.

| Command document | Concise purpose |
| --- | --- |
| [`composio-debug-bundle.md`](composio-debug-bundle.md) | Capture a sanitized Composio diagnostics bundle. |
| [`develop.md`](develop.md) | Run one or many tracker-backed programming tasks through canonical delivery. |
| [`project-domain-investigate.md`](project-domain-investigate.md) | Retrieve bounded, evidence-backed project domain context before development. |
| [`os-add-bug.md`](os-add-bug.md) | Route and capture a bug or missed enforcement. |
| [`os-add-spec.md`](os-add-spec.md) | Add a canonical Spec through project policy. |
| [`os-auto-add-feature.md`](os-auto-add-feature.md) | Legacy feature alias for automatic Spec intake. |
| [`os-auto-add-spec.md`](os-auto-add-spec.md) | Persist a long OS-shaping request as a Spec packet. |
| [`os-automation-control.md`](os-automation-control.md) | Inspect or operate the guarded automation control loop. |
| [`os-artifact-naming.md`](os-artifact-naming.md) | Configure and transactionally migrate date-prefixed durable entity names. |
| [`os-capture-plan.md`](os-capture-plan.md) | Capture future work into canonical project work-items. |
| [`os-chain.md`](os-chain.md) | Define, inspect, or test event-chain rules. |
| [`os-claude-desktop-bridge.md`](os-claude-desktop-bridge.md) | Build or audit the optional Claude Desktop custom-skill and instruction package. |
| [`os-clean-worktrees.md`](os-clean-worktrees.md) | Reconcile terminal work and safely close stale worktrees. |
| [`os-client-automation-brief.md`](os-client-automation-brief.md) | Turn client discovery into a bounded automation brief. |
| [`os-cockpit.md`](os-cockpit.md) | Build or open the local engineering cockpit. |
| [`os-context-audit.md`](os-context-audit.md) | Audit routed context quality and missing contracts. |
| [`os-control-plane-bootstrap.md`](os-control-plane-bootstrap.md) | Bootstrap a guarded filesystem/Notion control plane. |
| [`os-create-automation.md`](os-create-automation.md) | Create a reusable, maturity-gated automation. |
| [`os-create-instance-program.md`](os-create-instance-program.md) | Create a domain-local program instance. |
| [`os-create-program.md`](os-create-program.md) | Create a reusable shared OSProgram. |
| [`os-create-workflow.md`](os-create-workflow.md) | Create a reusable workflow contract and run surface. |
| [`os-discover-rooms.md`](os-discover-rooms.md) | Discover and route among installed OS rooms. |
| [`os-doc-config.md`](os-doc-config.md) | Plan document placement before filesystem or Notion writes. |
| [`os-docs-upkeep.md`](os-docs-upkeep.md) | Detect documentation drift and run upkeep. |
| [`os-doctor.md`](os-doctor.md) | Diagnose installed OS structure and subsystem health. |
| [`os-end-chat.md`](os-end-chat.md) | Finalize a substantial task with receipts and next action. |
| [`os-event.md`](os-event.md) | Append, inspect, or replay durable OS events. |
| [`os-execution-fabric.md`](os-execution-fabric.md) | Inspect or validate the optional named-queue and bounded worker-pool program. |
| [`os-groom-spec.md`](os-groom-spec.md) | Turn a rough Spec into implementation-ready work. |
| [`os-gui.md`](os-gui.md) | Open the local Agentic OS Command Center desktop application. |
| [`os-heartbeat.md`](os-heartbeat.md) | Operate runtime heartbeat definitions and checks. |
| [`os-integration-setup.md`](os-integration-setup.md) | Prepare or diagnose an external integration. |
| [`os-library.md`](os-library.md) | Create, migrate, inspect, and validate the versioned object library. |
| [`os-new-feature.md`](os-new-feature.md) | Legacy alias for canonical Spec intake. |
| [`os-notify.md`](os-notify.md) | Send one governed local macOS notification for an operator-actionable condition. |
| [`os-notion-org.md`](os-notion-org.md) | Audit or reconcile the verified Notion organization. |
| [`os-operator-resource.md`](os-operator-resource.md) | Query typed read-only Program and Automation operator projections. |
| [`os-resource-registry.md`](os-resource-registry.md) | Refresh or read the atomic first-class resource snapshot used by Command Center. |
| [`os-ps.md`](os-ps.md) | Show Agentic OS process and runtime state. |
| [`os-quiet-run.md`](os-quiet-run.md) | Run long commands with artifact-backed status. |
| [`os-route.md`](os-route.md) | Resolve a request to the narrowest OS room. |
| [`os-run-build-runner.md`](os-run-build-runner.md) | Execute a resumable, board-backed build queue. |
| [`os-run-log.md`](os-run-log.md) | Create or close a durable run log. |
| [`os-run-queue.md`](os-run-queue.md) | Inspect and operate the file-backed run queue. |
| [`os-runtime-init.md`](os-runtime-init.md) | Initialize runtime registries and local state. |
| [`os-self-improvement.md`](os-self-improvement.md) | Review evidence and propose governed OS improvements. |
| [`os-status-report.md`](os-status-report.md) | Generate a receipt-backed recent-work status report. |
| [`os-sync-notion.md`](os-sync-notion.md) | Plan or run verified Notion projection sync. |
| [`os-update.md`](os-update.md) | Plan, apply, inspect, or roll back an OS update. |
| [`os-watch-source.md`](os-watch-source.md) | Configure and poll connected source watchers. |
| [`os-work-state.md`](os-work-state.md) | Maintain SQLite-backed canonical work state and the bounded active-now projection. |
| [`system-tool-registry.md`](system-tool-registry.md) | Inspect or update host-safe tool declarations. |

When adding or removing a command, update this table and the owning registry or
capability code in the same change.
