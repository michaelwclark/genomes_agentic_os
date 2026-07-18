# Execution Fabric Documentation Contract

Document queue names, accepted task classes, worker-pool limits, provider
budgets, retry/dead-letter policies, ownership, activation state, and rollback
receipts. Never include credentials or backend connection secrets.

All producers use `append_run_queue_item`; all operator readers use the selected
`runtime.queue_mode`. The Command Center snapshot exposes queue depth, running
tasks, failures/dead letters, live workers, unhealthy workers, named queues,
and worker pools. The supervisor claims a bounded concurrent batch: five
background slots from six total, with one slot reserved for interactive Command
Center work. `max_interactive_running` explicitly caps Command Center turns
only in Execution Fabric mode, preserving legacy filesystem concurrency. Codex
and Claude are capped at two each; non-LLM work is capped at
four. Legacy shell-wrapped provider work is classified before routing, and
detached quiet-run/watcher children retain the outer lease until they finish.
Priority schedules are deduplicated and raised within the same batch instead of
serially blocking the supervisor. Managed Codex/Claude workers use ephemeral,
non-interactive sessions so background queue work does not accumulate resumable
manual sessions.

`agentic-os runtime snapshot` is the canonical point-in-time operator read. It
uses the same backend-neutral contract as Command Center and can filter task
rows by queue or status, emit deterministic JSON, or atomically write a JSON
receipt. Raw prompts, commands, payloads, references, free-form failure text,
and worker lease tokens are excluded. Execution Fabric reads share one SQLite
read transaction, while filesystem totals and rows derive from one parsed YAML
document. Command Center expands the headline health strip into an interactive
queue, pool, worker, and task explorer backed by this contract. Its filters are
explicitly scoped to the latest-200 task sample; use CLI filters or `--all` for
exhaustive evidence.

Hourly health enforcement writes local receipts and, only when unhealthy,
creates one idempotent, directly leased Codex self-heal task and one governed
system notification per incident fingerprint.
