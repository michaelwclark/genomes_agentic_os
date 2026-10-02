# Run Log Datalake operations guide

> **Status (2026-08-08):** Documentation baseline only. The Rubicon Run Log
> Datalake is not yet provider-readback verified as cut over. Treat the
> filesystem evidence path as the current operational source until AGE-154,
> AGE-155, AGE-156, and AGE-157 have independent terminal receipts.

## Audience and ownership

- **Audience:** Agentic OS operators and maintainers diagnosing run evidence.
- **Owner:** Agentic OS platform maintainers (Rubicon: Run Log Datalake).
- **Freshness:** Re-verify after every cutover, migration, retention-policy, or
  provider change; the `Status` line is the freshness marker.
- **Source of truth:** The installed Agentic OS source and its provider-read
  receipts. This page is an operator projection, not a replacement for those
  sources.

## What the datalake will do

The target design stores canonical run, conversation, watcher, alert,
heartbeat, report, and test evidence behind a provider-neutral application
port. MongoDB is an adapter, not lifecycle or queue authority. Evidence must
retain originating host identity and remain queryable without exposing
credentials or private local paths.

## Current behavior and safe operator posture

1. Use the existing filesystem run-log and receipt surfaces for current
   incident reconstruction.
2. Do not claim MongoDB cutover, historical coverage, retention enforcement,
   cleanup, or analytics completeness without an exact provider readback.
3. Do not delete filesystem evidence. Cleanup requires an import manifest,
   count/integrity comparison, rollback plan, and independent readback.
4. Keep examples and external links public-safe; never copy secrets, tokens,
   customer data, or machine-local paths into an operator page.

## Target write and outage flow

```mermaid
flowchart LR
  W[Registered writer] --> P[Evidence application port]
  P -->|healthy backend| D[(Configured datastore)]
  P -->|bounded non-blocking fallback| O[Atomic local outbox]
  O --> R[Replay with original host identity]
  R --> D
```

The caller must remain within the configured ingress bound during backend
outage. Replay is idempotent and must produce a receipt before any cleanup is
considered.

## Required evidence before this page is marked current

The operator-facing Notion child page and this source page may be marked
current only after the following are independently read back:

- query service parity across CLI, API, and MCP (AGE-154);
- writer cutover and outage/replay behavior (AGE-155);
- per-model retention, holds, compaction, and cleanup receipts (AGE-156);
- historical migration coverage and guarded filesystem cleanup (AGE-157);
- host attribution, source revision, installed-runtime revision, and owner;
- provider identity, parent, title, rendered headings, and content.

Until then, this document intentionally describes the boundary and the
verification gate rather than planned behavior as deployed behavior.

## Atomic outbox building block (AGE-153, implementation in progress)

The provider-neutral `run_evidence.outbox.FilesystemOutbox` is a local recovery
buffer. It is not connected to production writers; the asynchronous ingress,
configuration binding, transport deadlines and full acceptance validation remain
part of AGE-153. Existing writer behavior is unchanged.

- `put(record)` returns a durable envelope key only after a private atomic file
  write, file fsync and directory fsync. An exception is not an acknowledgement.
- Explicit `OutboxPolicy` bounds count, bytes, individual envelopes, replay batch,
  lease duration and retry budget. One item slot and one maximum-sized record
  are reserved for atomic updates. Quarantine and interrupted temporary files
  consume the same quota; full or busy storage raises a visible typed error.
- Replay claims use unique fencing tokens and expiring leases. Provider I/O
  occurs after releasing the local lock. Expired workers cannot retire another
  worker's claim. Restarted workers can replay previously durable records.
- Replay persists through `RunLogStore`, reads back identity and content through
  that same port, and only then removes the local envelope. Failed writes or
  mismatched readback retain evidence, use capped backoff and eventually
  quarantine. The error code never includes raw provider diagnostics.
- Original timestamps, host, correlation, work/run identity and payload metadata
  stay in the frozen envelope. Corrupt envelopes fail visibly and are preserved
  for operator recovery; automated corrupt-file quarantine is still outstanding.
- `status()` reports count, bytes, pending/claimed/quarantined items, interrupted
  temporary files and oldest age. Nothing prunes retained evidence automatically.

Use only an owned local directory with cooperative writers. Network filesystems,
malicious local file replacement, arbitrary blocked provider calls, automatic
poison-file recovery and end-to-end producer latency are not validated by this
building block. No live outbox or datastore is needed for its tests.

Run `tests/test_run_evidence_outbox.py` with a fresh item-owned pytest temporary
root. It covers restart, process exit, duplicate persistence, lease fencing,
concurrent-process quota enforcement, readback mismatch, backoff/quarantine,
fsync failures, serialization, capacity and private file permissions. Existing
port and MongoDB adapter conformance tests remain adjacent regression coverage;
a live disposable MongoDB profile is a separate opt-in gate.
