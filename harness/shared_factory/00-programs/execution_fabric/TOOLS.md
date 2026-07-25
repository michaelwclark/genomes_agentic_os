# Execution Fabric Tools

| Tool | Purpose |
| --- | --- |
| `/execution-fabric` | Inspect or plan this optional program. |
| `agentic-os resource-registry refresh` | Refresh installed program discovery. |
| `agentic-os runtime snapshot` | Capture backend-neutral queue, pool, worker, and safe task state. |
| `agentic-os runtime config show` | Show the redacted effective policy and every source layer. |
| `agentic-os runtime config status` | Show the effective config source, fingerprint, canonical dependency paths, and runtime drift. |
| `agentic-os runtime config diff` | Compare the effective fingerprint with local catalog and remote policy readback. |
| `agentic-os runtime config validate` | Schema-check the canonical Execution Fabric instance configuration and cross-references. |
| `agentic-os runtime config reconcile` | Dry-run or transactionally apply queue, pool, limit, lease, and retry changes while the fabric is authoritative. |
| `agentic-os runtime config reload` | Guardedly reload remote policy with an expected fingerprint, admin credential, readback, and durable receipt. |
| `agentic-os gui open` | Open Command Center's Execution Fabric page for queues, workers, runs, effects, alarms, healing, config drift, and failover state. |
| `agentic-os runtime submit` | Dry-run or idempotently admit a task through the configured local/remote transport. |
| `agentic-os runtime work` | Run a bounded, heartbeat-driven host-native worker; remote mode supports configured concurrency. |
| `agentic-os runtime status` | Read normalized queue, worker, task, and recent-run state from local/degraded or remote state. |
| `agentic-os runtime queue-mode` | Inspect, plan, apply, or roll back the selected backend. |
| `agentic-os runtime doctor` | Validate the selected runtime backend and registries. |
| `agentic-os validate` | Validate the installed OS contract. |
| `npm run start:api` | Run only the remote request-serving control-plane role; it does not observe or heal. |
| `npm run start:observer` | Persist and version remote health findings plus alarm intents without repairing. |
| `npm run start:healer` | Consume only allow-listed findings with fenced, bounded repair receipts. |
| `npm run start:scheduler` | Persist and admit deterministic interval occurrences under leader and epoch fencing. |
| `installers/execution-fabric/bin/dispatch-alarms.sh` | On bigmac, lease durable alarm intents and deliver them through the canonical Agentic OS notifier. |
| `installers/execution-fabric/bin/candidate-reporter-health.sh` | Verify the local PostgreSQL role, upstream WAL evidence, reporter freshness, and expected active/standby mode. |

Remote transport requires HTTPS and the distinct environment variables named
by `submit_token_env`, `worker_token_env`, `observer_token_env`, and
`admin_token_env`. Each value may instead come from the corresponding `_FILE`
environment variable for an operator-owned secret mount. Never put a
bearer token in YAML, task payloads, commands, logs, or documentation. No
managed queue backend is activated by this definition alone.
Observer credentials are GET-only. Provider effect consumers and alarm
dispatchers use separately provisioned credential maps bound to identity and
source; those deployment-only filenames stay in canonical `runtime.env`, not
in the editable queue-policy YAML.
