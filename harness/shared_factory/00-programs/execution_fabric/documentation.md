# Execution Fabric Documentation Contract

Document queue names, accepted task classes, worker-pool limits, provider
budgets, retry/dead-letter policies, ownership, activation state, and rollback
receipts. Never include credentials or backend connection secrets.

All producers use `append_run_queue_item`; all operator readers use the selected
`runtime.queue_mode`. The Command Center snapshot exposes queue depth, running
tasks, failures/dead letters, live workers, unhealthy workers, named queues,
and worker pools. The supervisor claims a bounded concurrent batch: five
background slots from six total, with one slot reserved for interactive Command
Center work. Codex and Claude are capped at two each; non-LLM work is capped at
four. Legacy shell-wrapped provider work is classified before routing, and
detached quiet-run/watcher children retain the outer lease until they finish.
Priority schedules are deduplicated and raised within the same batch instead of
serially blocking the supervisor. Managed Codex/Claude workers use ephemeral,
non-interactive sessions so background queue work does not accumulate resumable
manual sessions.

Hourly health enforcement writes local receipts and, only when unhealthy,
creates one idempotent, directly leased Codex self-heal task and one governed
system notification per incident fingerprint.
