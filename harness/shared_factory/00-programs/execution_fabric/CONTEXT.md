# Execution Fabric Context

Execution Fabric is the optional shared program for named queues, bounded worker
pools, admission control, retries, leases, and dead-letter handling across LLM
and non-LLM work. Its installed definition is available for discovery in every
Agentic OS instance. The compatibility default remains the existing filesystem
YAML run queue.

The source definition owns policy and schemas. Installed control-plane and run
surfaces own mutable configuration, tasks, worker observations, and receipts.
