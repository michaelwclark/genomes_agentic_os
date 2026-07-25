# OSProgram: Execution Fabric

## Purpose

Provide an optional, instance-wide execution fabric for named queues and bounded
worker pools so automations, workflows, programs, and interactive sessions can
share capacity without unbounded agent launches or unrelated work blocking one
global queue.

## Status

Installed and discoverable, but inactive by default. The compatibility mode is
the existing filesystem-backed YAML queue. Program presence never enables the
managed execution path.

## Ownership

The source package owns the reusable program contract, schema, shipped defaults,
and activation requirements. Each installed Agentic OS instance owns the
editable `harness/config/execution-fabric.yml`, selected mode, runtime state,
receipts, and backend secrets. Host identity, host-routing policy, and alert
policy remain in their canonical existing registries.

## Modes

| Mode | Meaning |
| --- | --- |
| `filesystem` | Continue using the existing YAML run queue and runtime commands. |
| `execution_fabric` | Route admitted work through named managed queues and worker pools. |

Mode changes must be explicit, validated, reversible, and single-writer. A
future backend may use a local coordinator or an external workflow engine, but
producers consume the Agentic OS queue contract rather than a vendor API.

## Activation gate

Before `execution_fabric` is enabled, run the guarded queue-mode preflight. The
implementation enforces atomic claims, idempotent enqueue, bounded
global/provider/queue concurrency, leases and recovery, retry budgets, dead
letters, authoritative backend reads, health observability, self-heal routing,
system notifications, concurrent supervisor batches, interactive capacity
reservation, detached-child lease retention, and rollback blockers for
unprojected work.

Remote activation additionally requires independent API, observer, healer,
and alarm-dispatcher roles. Business processing never evaluates health or
sends alerts. Observation never repairs. Healing is deterministic and limited
to configured allow-listed actions with epoch fencing, idempotency, cooldown,
hourly budget, and before/after verification. The alarm dispatcher is the only
role that crosses into the canonical Agentic OS notification seam.

Transient timeouts, provider throttling and 5xx responses, and recognized
network transport failures use bounded exponential backoff. Unknown command
failures remain terminal by default. The five-minute default supervisor cadence
keeps queue pickup within AutoDev's documented 5-10 minute expectation without
requiring an always-on broker on a laptop.

The supervisor also creates one daily online SQLite snapshot after validating
it with `PRAGMA integrity_check`; seven valid snapshots are retained under the
installed shared-factory run-log tree. Operators can request the same guarded
operation with `agentic-os state backup --root <root> --apply`.

## Operator projection

Command Center is current-state-first. It shows running work explicitly,
defaults the task explorer to active states, and projects only live or unhealthy
worker rows. Lifetime task failures and retired ephemeral-worker registrations
remain durable history, but are summarized and labeled as history rather than
presented as current incidents. Canonical identifiers remain available in task
detail while safe display names are humanized for the primary tables.
