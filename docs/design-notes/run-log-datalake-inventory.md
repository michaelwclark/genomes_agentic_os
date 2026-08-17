# Run Log Datalake Inventory and Storage Decision

Status: accepted design baseline for AGE-150 / AGE-151  
Verified: 2026-08-03 on bigmac

## Decision

Agentic OS needs two distinct data planes:

1. Authoritative lifecycle, queue, lease, fencing, idempotency, and cursor state stays behind Rubicon's `ControlPlaneStore` (SQLite for a local install; PostgreSQL for a shared profile).
2. High-volume, heterogeneous, append-oriented run evidence moves behind a provider-neutral `RunLogStore`. MongoDB on genomesbox is the first shared adapter because this workload is document-shaped, cross-host, schema-versioned, and analytics-oriented.

MongoDB is not control-plane truth. SQLite is not the shared evidence lake. A local filesystem outbox is the failure buffer, not a browseable archive.

The canonical model inventory, ordered routing priority, source patterns, indexes, payload limits, redaction profile, age limit, count limit, compaction, and hold behavior live in `harness/config/run-evidence.yml`. Routing priorities are unique so overlapping patterns resolve deterministically. Changing its top-level `backend` value is the only caller-visible datastore selection.

## Genomesbox datastore preflight

The AGE-151 read-only preflight confirmed MongoDB 8.0.20 with WiredTiger and the normal 16 MiB BSON limit. The service is healthy but intentionally listens only on `127.0.0.1:27017`; the local shell currently connects without an authenticated user. That is not an acceptable cross-host production posture and must not be "fixed" by exposing the unauthenticated listener.

AGE-152 must provision least-privilege SCRAM credentials, keep credential values outside source and receipts, bind only to loopback plus the canonical private host interface after authentication is verified, and prove both bigmac connectivity and rollback before enabling remote ingestion. Application code still imports only `RunLogStore`; only the Mongo adapter and composition root may use the driver. If this infrastructure preflight fails, writers stay nonblocking by spilling to the bounded outbox.

## Observed bigmac pressure

The shared run-log root contained these immediate-entry counts during the baseline scan:

| Family | Immediate entries | Observed shape | Classification |
| --- | ---: | --- | --- |
| `runs` | 74,778 | one directory per run, normally containing `run-log.yml` | durable evidence |
| `interim-executor` | 5,998 | timestamped `.log` files | durable evidence |
| `async-runs` | 2,403 | state, summary, output, events, command, preflight, terminal receipt | durable evidence |
| `automation-control` | 2,372 | one YAML action record per operation | durable evidence |
| `runtime-health` | 633 | JSON plus Markdown report pairs | durable evidence |
| `harness-runs` | 126 | harness transcript text | durable evidence with strict redaction |
| `resource-actions` | 58 | YAML resource mutation receipts | durable evidence |
| `run-queue-prune` | 25 | YAML maintenance receipts | durable evidence |
| `state-backups` | 18 | SQLite/JSON backups plus latest pointer | authoritative backup reference; do not embed raw DB bodies |
| `events` | 14 | event YAML | compatibility evidence; canonical event state remains control-plane owned |

The `runs` directory alone had 74,762 immediate subdirectories. This representation makes normal browsing and recursive inventory materially slow; multiple bounded scans exceeded 30 seconds. That is direct evidence that per-run directories are no longer a viable query surface.

The completed read-only baseline (`080326-age-151-run-evidence-inventory-v2`) traversed the entire shared root successfully and found **114,358 files**, **78,964 directories**, and **1,504,091,372 bytes**. The largest families by file count were `runs` (75,079 files), `async-runs` (16,747), `source-events` (10,204), `interim-executor` (5,998), `runtime-health` (2,574), and `automation-control` (2,372). YAML alone accounted for 87,667 files. The baseline JSON and terminal receipt live in the AGE-151 work-item packet so later migration proofs can bind to this exact source snapshot without treating the installed projection as versioned source. The public-safe [inventory evidence index](age-151-inventory-evidence.md) records their immutable hashes and summary metadata for tracker linkage.

## Cross-root families

The cutover inventory also covers domain run logs, automation/workflow run folders, conversation sidecars, work-item async/test/QA evidence, PR watch receipts, reports, metrics, alerts, heartbeats, failures, source events, maintenance receipts, provider readbacks, and derived work artifacts. Each family has an explicit model or an explicit artifact-reference policy in the canonical configuration.

The same configuration contains the current writer registry: source paths, owning subsystem, target model keys, shared replacement boundary, and AGE-155 cutover owner. This is the enforcement input for the direct-writer guard; read-only consumers are intentionally not treated as writers.

## Migration and cleanup constraints

- Every imported object is bound to a canonical host record; `bigmac` is the initial host.
- Historical import is resumable and idempotent by stable source identity plus content SHA-256.
- Secrets, malformed documents, oversized payloads, and unknown models are quarantined with reasons.
- Source cleanup occurs only after target counts, hashes, sampled bodies, indexes, host links, and queries read back successfully.
- Every model has both a maximum age and maximum object count. Holds and active/high-value failure evidence override ordinary cleanup according to the model policy.
- Direct high-volume filesystem writers are retired vertically with shadow parity and rollback, not with a single blind delete.

## Architecture gate

Before implementing any AGE-150 child issue, agents must read `AGENTS.md`, `docs/README.md`, `docs/architecture/system-architecture.md`, and the Ledgerline/LOSMON reference architecture. Services depend on ports, adapters own provider behavior, construction happens in one composition root, dependencies are explicit, and tests exercise contracts at the immediate boundary.

## AGE-152 storage boundary and operator handoff

**Audience:** Agentic OS maintainers and operators preparing the Run Log Datalake.
**Source of truth:** `harness/config/run-evidence.yml` selects the supported backend and model policy; `harness/config/hosts.yml` owns the bootstrap host record.
**Owner and freshness:** The Run Log Datalake maintainers update this note whenever the port, backend configuration, host registry, or retention contract changes; its implementation state is current at the AGE-152 PR head.

AGE-152 adds the provider-neutral `RunLogStore` contract, an in-memory implementation for contract tests, and a lazy MongoDB adapter. Application services use only the port. The MongoDB driver is constructed only by the composition root, which reads the single configured backend value and the environment-variable *name* for its connection URI. Credential values are never stored in configuration, documentation, or receipts.

The store validates host attribution and canonical model configuration, upserts and reads back the configured initial host (`bigmac`), supports idempotent imports, queries, aggregates, index setup, and retention operations. The MongoDB adapter keeps evidence collections separate from Rubicon lifecycle, queue, lease, fencing, and idempotency authority. Its integration tests are optional until an approved disposable, least-privilege MongoDB URI is supplied.

**Operational output:** this ticket ships a reusable source package and tests; it does not enable a remote listener, provision credentials, change a deployed backend, or migrate historical files. Before enabling cross-host ingestion, the operator must complete the authenticated private-interface connectivity and rollback proof described above. Until that proof exists, later writer work must retain the bounded-outbox fallback.

The canonical local design note is the correct destination for this implementation because no project Doc Config routes this operational/source-package documentation to Genome's Notion. The separate AGE-158 ticket owns the approved Genome's Notion operations page after the cutover dependencies are satisfied.
