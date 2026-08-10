# 18 · Execution Fabric

Capture the selected backend at one moment without mutating it:

```bash
agentic-os runtime snapshot --root ~/agentic_os
agentic-os runtime snapshot --queue codex --status queued --json --root ~/agentic_os
agentic-os runtime snapshot --output runtime-snapshot.json --root ~/agentic_os
```

The snapshot contains aggregate status, named queues, worker pools, safe worker
metadata, and a bounded task sample. Command Center consumes the same contract
for its interactive Execution Fabric detail view. Fabric reads use one SQLite
read transaction and filesystem reads use one parsed YAML document, so totals
and rows describe the same instant. Raw task payloads, commands, prompts,
references, free-form failure text, and lease tokens are intentionally not
projected. Command Center labels its latest-200 task sample and applies filters
only to that sample; the CLI supports queue/status filtering and `--all` when
an exhaustive receipt is required.

Execution Fabric is an optional shared OSProgram for named queues and bounded
worker pools. It is installed into every Agentic OS root, but presence never
activates it:

```toml
enabled = false

[runtime]
queue_mode = "filesystem"
```

This preserves existing installs and upgrades. If `runtime.queue_mode` is
missing from the installed runtime registry, the effective mode is still
`filesystem`.

## What ships

The editable installed policy is the discoverable root-level harness config:

```text
harness/config/execution-fabric.yml
```

The source-owned program under
`harness/shared_factory/00-programs/execution_fabric/` contains the operating
contract and compatibility definition assets. The effective instance config
contains:

- one explicit `transport` selector (`local`, authenticated `remote`, or
  `remote_with_local_fallback`) and its
  control-plane URL/timeouts plus distinct submit, worker, observer, and admin
  token environment-variable names;
- five bounded queue definitions for Codex, Claude, Team PR review, LOS
  environment reconciliation, and host-local non-LLM work;
- matching worker-pool definitions with worker, task, lease, and retry limits;
- JSON Schemas for queue configuration, worker pools, and task envelopes;
- routing, CRUD, runbook, testing, and rollback contracts.

Lists with canonical identifiers merge by stable identity: queues and worker
pools use `id`, while `task_routes` use `task_type`. A host or invocation
overlay that changes one task route therefore preserves every unrelated route.

Mutable state never lives in that program folder. Filesystem mode owns
`run-queue.yml`; execution-fabric mode owns the `run_queue`, queue, pool, and
worker tables in local `state.db` when `transport.mode: local`. In remote mode,
PostgreSQL is the canonical task/run/effect ledger and BullMQ/Valkey is the
delivery signal; workers never treat Valkey as the source of truth.

Inspect configuration provenance before editing or reconciling:

```bash
agentic-os runtime config status --root ~/agentic_os --json
agentic-os runtime config show --root ~/agentic_os --json
agentic-os runtime config diff --root ~/agentic_os --json
agentic-os runtime config validate --root ~/agentic_os
```

The status includes the effective source, schema, content fingerprint, drift,
and paths to the canonical host identity, host-routing, and alert registries.
Those existing registries remain authoritative; Execution Fabric does not
create parallel host or alert configuration.

## Local and cross-host transport

Fresh installs remain on the explicit local/degraded transport:

```yaml
execution_fabric:
  transport:
    mode: local
    control_plane_url: null
    request_timeout_seconds: 20
    long_poll_seconds: 20
    submit_token_env: AGENTIC_OS_EXECUTION_FABRIC_SUBMIT_TOKEN
    worker_token_env: AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN
    observer_token_env: AGENTIC_OS_EXECUTION_FABRIC_OBSERVER_TOKEN
    admin_token_env: AGENTIC_OS_EXECUTION_FABRIC_ADMIN_TOKEN
```

For cross-host operation, use an HTTPS endpoint reachable through Tailscale
Serve or trusted ingress and store only the environment-variable name in YAML:

```yaml
execution_fabric:
  transport:
    mode: remote
    control_plane_url: https://genomesbox.example.ts.net
    request_timeout_seconds: 20
    long_poll_seconds: 20
    submit_token_env: AGENTIC_OS_EXECUTION_FABRIC_SUBMIT_TOKEN
    worker_token_env: AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN
    observer_token_env: AGENTIC_OS_EXECUTION_FABRIC_OBSERVER_TOKEN
    admin_token_env: AGENTIC_OS_EXECUTION_FABRIC_ADMIN_TOKEN
```

The Python client refuses remote mode if the URL is not HTTPS, loopback HTTP,
or a literal Tailscale CGNAT (`100.64.0.0/10`) HTTP address; it also refuses
credentials embedded in the URL or an empty named token environment variable.
Each credential can come from the named variable or its `_FILE` counterpart,
which supports Docker and Kubernetes secret mounts without copying tokens into
the process definition. Defining both forms is rejected.
Arbitrary LAN/public HTTP and hostname-based plain HTTP are rejected. Tailscale
Serve HTTPS remains preferred. The service deployment must enforce bearer
authentication on every `/api/v1` task, worker, attempt, effect, and snapshot
route; client-side headers alone are not an authorization boundary.

### Personal genomesbox-primary fallback

For a personal two-host setup that values continuity over consensus-grade HA,
use the explicit fallback transport on bigmac:

```yaml
execution_fabric:
  transport:
    mode: remote_with_local_fallback
    control_plane_url: http://100.64.0.2:3180
    request_timeout_seconds: 20
    long_poll_seconds: 20
    submit_token_env: AGENTIC_OS_EXECUTION_FABRIC_SUBMIT_TOKEN
    worker_token_env: AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN
    observer_token_env: AGENTIC_OS_EXECUTION_FABRIC_OBSERVER_TOKEN
    admin_token_env: AGENTIC_OS_EXECUTION_FABRIC_ADMIN_TOKEN
    fallback:
      failure_threshold: 3
      state_path: harness/shared_factory/00-control-plane/execution-fabric-fallback.json
```

Personal activation preflights and starts three client-plane jobs on bigmac:
the remote host worker, the durable alarm dispatcher, and the independent
fallback watchdog. The preflight binds worker ID, bootstrap ID, host, pool,
queue set, capability set, and concurrency to canonical policy; validates the
shipped routes and distinct scoped token files; and requires a routable signed
gateway. It does not require standby PostgreSQL/Valkey/MinIO or local copies of
the control plane's credential maps. The server verifies the exact bootstrap
and dispatcher bindings when each client connects.

The watchdog runs `runtime fallback probe --apply` once per minute.
Three consecutive readiness failures latch bigmac onto its existing local
durable SQLite queue. The latch is durable across process and host restarts.
New bigmac work continues locally; work already accepted by genomesbox remains
there until the primary returns. This deliberately avoids retrying an uncertain
remote admission into a second backend.

Recovery never switches back automatically. Inspect the latch and perform the
readiness-gated failback explicitly:

```bash
agentic-os runtime fallback status --root ~/agentic_os --json
agentic-os runtime fallback probe --root ~/agentic_os --apply --json
agentic-os runtime fallback activate --reason maintenance --root ~/agentic_os --apply --json
agentic-os runtime fallback failback --root ~/agentic_os --apply --json
```

This mode makes no automatic split-brain or zero-data-loss claim. It is for a
personal harness: genomesbox owns the shared ledger when healthy, while bigmac
can continue its own automations locally during an outage. Alerts use the
canonical `runtime.execution_fabric.health` route and failback requires proven
genomesbox readiness.

Submit a remote-safe, commandless task, run a bounded worker, and inspect the
same contract:

```bash
agentic-os runtime submit \
  --queue codex \
  --task-type llm.codex \
  --idempotency-key age-123-implementation-v1 \
  --payload-json '{"work_item_id":"AGE-123","instruction_ref":"harness/shared_factory/01-inbox/AGE-123.md"}' \
  --root ~/agentic_os

# The first command is a dry-run. Repeat it with --apply after review.
agentic-os runtime submit ... --apply

agentic-os runtime work \
  --queue codex \
  --capability codex.task \
  --max-concurrency 2 \
  --root ~/agentic_os \
  --apply

agentic-os runtime status --root ~/agentic_os --json
```

`runtime work` registers the host, renews worker and active-attempt leases,
long-polls for assignments, executes only the existing governed local runtime
targets, and reports success/failure to the durable ledger. It writes a local
run receipt below
`harness/shared_factory/06-runs-and-logs/execution-fabric/worker-runs/`.
`--once` is useful for a smoke test; `--max-tasks N` creates a bounded batch.
Worker concurrency defaults from the selected queue pools and global admission
limit and can be lowered per process.

Raw `script` and `process` payloads remain available only to the local/degraded
transport. The shared remote control plane admits only closed-schema task
routes with a registered domain worker; it never accepts an arbitrary command
from a task producer.

## First-class consumer routes

Team PR review uses `los.team_pr.ai_review.v1` on `pr_reviews`. The Notion
button adapter snapshots repository, PR number and URL, expected head SHA, base
branch, source/Jira key, `review_no_merge` mode, title, Notion page ID, and the
provider-read GitHub author into the closed payload. Its idempotency key binds
repository, PR, head SHA, source key, and review mode, so repeated button
observations return the same task instead of
starting duplicate reviews. The `team_pr_ai_review` worker invokes the
installed portable helper at
`lib/programs/domains/los/team_pr_sync/scripts/team_pr_review_fabric.py`.
That helper reads the canonical LOS project policy from
`domains/los/02-projects/los_app_los_django/config/development.yml`, routes
team-authored PRs through Review Self semantics and other PRs through Review
Others semantics, and delegates both to canonical PR review. The helper freezes
one terminal-packet resolution in a create-once review-only snapshot; it never
runs Auto-Dev with `--apply` or writes the shared SQLite work registry.
The worker first persists review intent keyed by repository, PR, immutable
head, source ticket, and review mode. It reuses the helper's terminal receipt
after interruption and derives a stable effect key from that identity.
Repository, head SHA, and source-key casing are normalized before the worker
and helper derive that identity, preventing case drift from splitting one
admitted review across multiple run directories.
The worker uses a per-review-identity file lock to reject overlapping attempts
as retryable, even
when an upgrade leaves two task IDs for the same immutable review. The helper
must accept the controller-derived review mode, full-identity run ID, and exact
summary path before it performs provider work. Corrupt receipts fail closed;
transient filesystem read, write, and lock errors remain retryable. Receipt paths use the full
identity digest, intent writes fsync file and directory state, and a durable
launch marker prevents a lease retry from starting a second helper while an
orphaned helper may still be within its nominal timeout plus a ten-minute
grace. The review pool's ten-minute retry backoff and bounded attempt budget
ensure the last configured attempt lands after that fence instead of exhausting
the immutable task early, including when retries begin after an ambiguous
dispatch failure.
The paired helper records its PID in the same identity-bound marker before any
provider read. Controller and helper compare-and-replace operations share a
marker lock, so an exceptional dispatch cannot overwrite a concurrently
registered PID. A live PID remains fenced inside the age threshold, while a
dead PID permits immediate recovery. Spawn exceptions durably mark the launch
failed before returning a classified retryable error, and a validated helper
result terminalizes the marker as `succeeded`.
PID reuse is rejected by verifying the live process command against the exact
helper script and full-identity run ID; only that verified helper remains
fenced beyond the age grace.
Create-once losers revalidate the winning intent before using it. The
trusted controller revalidates the immutable provider head before and after
review, and binds every recovered summary's run ID and source key back to the
admitted identity; Agentic OS and Codex receive no provider credential. A
changed head
returns `superseded` and creates no effect. Only the route-derived
`notion.pr_review.update` effect
consumer may project a validated terminal review receipt back to Notion.
For upgrade compatibility, a task admitted before explicit `review_mode`
continues to emit the legacy `{type}:{source_key}:{head}` effect key. Current
tasks that carry `review_mode` emit the full-intent key. This transition rule
preserves control-plane dedup when a legacy effect was staged before a lost
completion acknowledgment. The first key chosen for an immutable review is
published create-once beside its helper summary; any later task shape reuses
that durable key instead of projecting the same result under another format.
The record is rederived and validated against its declared format before use.

Deployment order is strict: deploy this Agentic OS route before installing the
paired object-library producer. The producer emits explicit `review_mode`, and
the prior closed route correctly rejects that previously unknown field.
Quiesce and drain `pr_reviews` across the upgrade boundary before resuming the
producer. This prevents a legacy effect whose acknowledgment was lost from
being projected once more under the new full-review-intent effect key.

The review pool is two-wide on the pinned `bigmac` execution host. Its intent
files, helper marker, PID fence, and summaries are host-local; do not
distribute this pool across hosts until those records move into the shared
control plane. Remote task admission does not imply cross-host retry safety for this route. The
worker resolves the canonical fabric host ID and fails retryably before helper
execution when it is not `bigmac`, allowing a bounded retry on the pinned host.
Normal remote workers mechanically remove queues whose routes are all pinned
to other hosts before registration, so a non-`bigmac` worker does not claim
`pr_reviews` and spend the task's attempt budget.

The watcher state is runtime data at
`runtime/objects/programs/program/domain/los/team_pr_sync/state/team-pr-review-trigger-state.json`;
it does not belong beside root configuration or in the versioned program
object.

LOS deployment observation uses
`los.environment.deployment.observed` on `los_environment`. A producer records
the exact previous SHA, new SHA, environment, observation time, health URL, and
optional build. The `los_environment_reconcile` worker computes the exact
commit range, resolves included GitHub PRs and Jira keys, and emits durable Jira
actions. The label sequence is per Jira and per environment:
`env_beta`, `env_beta2`, `env_beta3`, and equivalently for QA, preprod, and
production. A second PR for a ticket in beta therefore increments only beta;
it does not imply a second QA or production visit. The first observed beta
arrival may also emit the configured Ready for QA transition.

Provider projection is a separate task route,
`los.jira.action.execute`, on the same queue. Its stable `action_id` and
`action_key` make Jira label and transition effects recoverable and idempotent.
Failures remain visible in the effect ledger and dead-letter flow, and may emit
`agentic_os.alert.publish`; the environment observer never hides a failed Jira
write behind a successful SHA observation.

The client also exposes fenced effect claim/deliver/fail operations for
provider-specific effect consumers. The observer token is read-only. Every
claim uses a separate credential bound to the consumer ID, source, and
non-empty owned `effect_types` allow-list; a projector must never claim
globally and skip unrelated effects. Completion can set bounded per-effect
`maxAttempts` and `baseBackoffSeconds`. The generic CLI worker does not invent
a provider handler or execute effect payloads blindly.

Alarm dispatchers likewise use a separate credential bound to dispatcher ID
and source. The static credential is used only to claim; deliver/fail uses the
short-lived claim token. Credential-map filenames live in the deployment
runtime environment, while queue and routing policy remains in the canonical
root-level `harness/config/execution-fabric.yml`.

In remote mode, API serving, health observation, deterministic healing, and
alarm delivery are separate processes over one PostgreSQL truth plane. Inspect
their durable projection through the supported CLI:

```bash
agentic-os runtime status --root ~/agentic_os --json
```

The status retains the existing `effects`, `healing`, and `alarms` fields and
adds `roleHealth`. Each API, observer, healer, and scheduler row reports the
database-approved and locally applied policy fingerprints, role instance,
last successful tick, last error, consecutive failures, and evaluated health.
Sustained scheduled-tick failure is therefore degraded or unhealthy even when
the process itself still exists. A first tick has a bounded startup grace, and
failure history survives instance replacement until a successful tick clears
it.
PostgreSQL also exposes a bounded reliability snapshot to authenticated
operators; Command Center does not infer healer health from the API process.

Queue snapshots include ready, delayed, retrying, running, dead-letter,
hourly-throughput, recent-failure-rate, oldest-ready-age, saturation, and
remaining-capacity values. Worker rows expose the current immutable session and
the ten most recent sessions. Run reports include every attempt plus safe
effect and artifact metadata, timing, errors, and the route-derived approval
and mutation classes. These are ledger projections; they are not reconstructed
from BullMQ.

## Configuration layers and scheduling

The only editable instance file remains
`harness/config/execution-fabric.yml`. Its deterministic precedence is release
default, instance, canonical host alias, then invocation override. Queue and
worker-pool arrays merge by stable `id`, never by list position. Host and
invocation layers may lower capacity and retry bounds but cannot raise them.
Every configured host overlay is validated even when it is not the current
host, preventing a dormant failover config from rotting quietly. A host alias
must exist in both canonical host identity and host-routing registries. Python
workers and Node services receive the same resolved `FABRIC_HOST_ID`; a
conflicting explicit worker ID is rejected instead of silently splitting one
machine into two logical hosts.

Admission supports hard `namespace_limits` and `host_limits`. Claim decisions
are serialized in PostgreSQL so concurrent workers cannot oversubscribe those
limits. Bounded priority aging prevents old low-priority tasks from starving;
namespace weights break ties by normalized running share.

The scheduler is its own independently supervised role. Each interval
occurrence receives a deterministic idempotency key, is persisted before task
admission, and is fenced by the current fabric epoch and unexpired leader
lease. Operators can inspect `/api/v1/snapshots/schedules`; schedule create,
update, enable, and disable operations remain admin-scoped. Normal primary and
synchronously durable promoted-standby profiles run it. A degraded-primary
takeover keeps the role supervised, but its leadership controller admits no
occurrence unless canonical `degraded_primary.allow_scheduler` is explicitly
enabled; occurrences remain durable and resume idempotently after redundancy
is restored.

## Selecting the writer

Inspect and preflight first:

```bash
agentic-os runtime queue-mode status --root ~/agentic_os
agentic-os runtime queue-mode plan execution_fabric --root ~/agentic_os
agentic-os runtime queue-mode apply execution_fabric --root ~/agentic_os
```

The final command above is still a dry-run. Apply explicitly:

```bash
agentic-os runtime queue-mode apply execution_fabric \
  --root ~/agentic_os --apply
```

Activation imports the existing YAML queue idempotently, initializes the local
SQLite schema, writes the selector atomically, and reads it back. Producers and
`runtime run-next` then use only the selected backend. A shared advisory lock
serializes queue mutation with mode changes.

After changing `harness/config/execution-fabric.yml`, preview and apply the
configuration reconciliation:

```bash
agentic-os runtime config reconcile --root ~/agentic_os
agentic-os runtime config reconcile --root ~/agentic_os --apply
```

Apply is rejected unless the fabric is the selected writer. Queue and pool
enablement, queue depth/concurrency, pool capacity, global/provider limits,
lease policy, and retry policy reconcile in one `BEGIN IMMEDIATE` transaction
and must read back with zero drift. Producers also run the same idempotent
reconciliation before enqueueing, so a valid edit cannot remain silently
stale.

The CLI can preview and prepare a fingerprint-fenced reload:

```bash
agentic-os runtime config diff --root ~/agentic_os --json
agentic-os runtime config reload \
  --root ~/agentic_os \
  --expected-fingerprint <sha256>
agentic-os runtime config reload \
  --root ~/agentic_os \
  --expected-fingerprint <sha256> \
  --rotation-id <witness-prepared-uuid> \
  --preparation-token-file <protected-token-file> \
  --apply
```

Apply requires the distinct admin credential. In the two-host remote fabric,
do not use that raw apply as the complete operation. Install the reviewed file
on both hosts, wait for both candidate reporters to publish its digest, and run
`installers/execution-fabric/bin/rotate-policy.sh OLD_SHA NEW_SHA` on the
witnessed leader. It coordinates the PostgreSQL authority and independent
witness at the exact leader and epoch. Policy files are mounted as one
read-only directory bundle so replacement cannot strand a role on a prior
single-file inode. Governed rotation force-recreates all long-lived policy
roles, requires exact candidate-fingerprint readback before witness commit,
and requires a fresh healthy tick from every role afterward. The API rejects every reload without
the signed, expiring witness preparation; signed leadership proofs bind the
policy digest and fence the handoff immediately. The preparation is
discoverable across hosts, so standby promotion can finish a
database-committed rotation after the old leader disappears. Witness commit is
not a client assertion: a fresh, healthy, non-leader streaming report must
prove the standby replayed the candidate digest on the prepared timeline and
upstream system. Unconsumed preparations remain listed after expiry. Expiry
blocks a new database reload but does not erase recovery of a change already
present on the synchronous standby. If the expired preparation never reached
PostgreSQL, fresh standby proof of the old digest conditionally aborts it before
promotion. The observation, lag measurement, and receiver timestamp must all
be strictly post-expiry. Only one unresolved preparation is allowed per
cluster. The command waits for renewed active leadership and writes the final
operator receipt. A stale role can adopt an identical durable fingerprint but
cannot replace it during startup.

The CLI's redacted preview and local reload receipts remain below
`harness/shared_factory/06-runs-and-logs/execution-fabric/config-reloads/`.

## Independent leadership witness

The witness is a provider-neutral, digest-pinned OCI service. Its canonical
portable deployment runs once on a declared third host, binds the process only
to that host's configured Tailscale IP, and stores authority in a durable
SQLite volume. SQLite uses WAL, `synchronous=FULL`, and
`BEGIN IMMEDIATE`; the mutation, replay receipt, and immutable audit stream
commit before the API returns. The shipped witness is SQLite-only and has no
cloud-provider deployment dependency.

Install and activate the portable assets explicitly:

```bash
installers/execution-fabric/install-witness.sh \
  --apply --source-root /path/to/genomes_agentic_os --release <release>
installers/execution-fabric/activate-witness.sh --apply
```

The installer enables a systemd timer for
`deploy/execution-fabric/witness/bin/monitor.sh`. It writes separate service
availability and drill-backed promotion-eligibility fields and emits the canonical
`runtime.execution_fabric.health` alert when liveness or durable readiness
fails. A container restart is not a readiness receipt.

For a personal genomesbox-owned installation without leadership transfer,
configure `FABRIC_WITNESS_MODE=standalone_primary`, enable the exact genomesbox
host in canonical `execution_fabric.standalone_primary`, and keep
`FABRIC_AUTO_FAILOVER=false` plus `FABRIC_ENABLE_PROMOTION=false`. The Linux
primary runner starts a digest-pinned, co-located signing service with durable
SQLite state and short renewable proofs. This preserves normal shared queue,
scheduler, and effect operation while genomesbox is healthy, but it is not an
independent failure domain and makes no HA claim. When genomesbox is offline,
shared work waits and bigmac's separate local fallback queue provides personal
continuity; bigmac never promotes the shared ledger.

If neither an independent witness nor the personal co-located authority is
desired, configure `WITNESS_MODE=manual_fail_closed`. No witness container
starts, `FABRIC_AUTO_FAILOVER` and `FABRIC_ENABLE_PROMOTION` must remain false,
and the system makes no two-node split-brain-safety claim. A ping between
genomesbox and bigmac cannot tell which side of a partition is authoritative.

If activation finds historical nonterminal SQLite rows that are missing from or
status-drifted against YAML, it refuses the switch. Reconcile from filesystem
mode before trying again:

```bash
agentic-os runtime queue-mode reconcile --root ~/agentic_os
agentic-os runtime queue-mode reconcile --root ~/agentic_os --apply
```

Reconcile is dry-run-first. Apply archives the exact affected rows, cancels only
missing stale nonterminal rows, aligns status drift to filesystem authority,
clears their leases, and writes a terminal receipt. It never deletes history.

## Admission and recovery

The SQLite substrate uses WAL mode and `BEGIN IMMEDIATE` transactions. A claim
must satisfy all of these limits before it changes a task from `queued` to
`running`:

- queue concurrency;
- worker-pool concurrency and maximum active workers;
- individual worker capacity and live worker lease;
- task due time and task lease availability.

`admission.max_interactive_running` separately caps native Command Center turns
only while `execution_fabric` is selected. Filesystem mode retains the legacy
uncapped cross-conversation behavior. The shipped value is two so the Team PR
review queue's two-worker contract is not silently collapsed by a stricter
global interactive ceiling.

At capacity, the task remains queued. Heartbeats extend worker and task leases.
Expired work is requeued until its attempt budget is exhausted, then moves to a
dead-letter state or configured dead-letter queue. Completion, retry,
cancellation, and pruning clear or respect leases transactionally.
An operator requeue preserves the task's monotonic attempt counter so its next
run receives a new run number; it clears terminal delivery/error state but never
reuses a prior `fabric_runs(task_id, run_number)` identity.

## Rollback

Rollback is also dry-run-first:

```bash
agentic-os runtime queue-mode rollback --root ~/agentic_os
agentic-os runtime queue-mode rollback --root ~/agentic_os --apply
```

Rollback is rejected if an active lease exists or if queued/running work exists
only in SQLite. This first slice does not pretend that an unsafe reverse export
has happened.

## Backend boundary

SQLite remains the included degraded coordinator because it provides safe local
concurrency without another service. The remote adapter uses the versioned
`/api/v1` control-plane contract; producers and workers do not connect directly
to PostgreSQL or Valkey. That boundary keeps host relocation and failover out of
individual workflows and automations. Switching `transport.mode` does not
silently migrate in-flight local tasks: activation and failover runbooks must
prove a fenced writer, reconcile outstanding work, and retain exact receipts.

## Run artifacts and release assets

Remote workers publish actual run reports through the control plane's
S3-compatible artifact contract. PostgreSQL records task, attempt, name,
content type, size, SHA-256, status, and portable URI. The service verifies the
stored object's bytes before making it available; a host-local receipt path is
never presented as cross-host proof. The PUT grant signs exactly the required
content length, content type, and SHA-256 metadata headers, including on MinIO.
When storage is unavailable, workers copy the immutable payload into their RWX
spool and retain only an attempt-scoped recovery token alongside its digest and
size. The current worker registration token is still required, so the recovery
token is not independently usable. A replacement pod with the same durable
bootstrap identity drains bounded batches, quarantines corrupt or exhausted
records, and publishes pending/due/quarantine health in its central heartbeat.

The Python wheel stays small and exposes
`genomes_agentic_os/resources/release-assets.json` so tools can discover the
matching release bundle. Deployments, installers, canonical config, schema,
image lock, checksums, SBOM, and emergency bundle are GitHub release assets and
remain in the source distribution. The tag workflow builds the control-plane,
leadership-witness, and worker images, then resolves the four reviewed
third-party source tags in
`deploy/execution-fabric/release-image-sources.json` to Linux AMD64/ARM64 index
digests. It records all seven exact repository digests, validates
Python/service/API versions plus config/schema/source-manifest hashes, and lets
exactly one job create the immutable GitHub release.

`execution-fabric-image-lock.json` is the sole authored lock. The released
`materialize-image-lock.sh` validates its exact seven-image schema and emits
the deterministic `FABRIC_*_IMAGE` projection used by Compose and recovery
tooling. Emergency bundles retain the JSON source and derived env projection,
then regenerate and compare the latter during validation. A recovery bundle
therefore cannot omit or independently substitute the witness or worker image.

Local release preflight:

```bash
python scripts/release/build-execution-fabric-release.py --validate-only
python scripts/release/build-execution-fabric-release.py \
  --output-dir dist/release \
  --control-plane-image ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-control-plane@sha256:DIGEST \
  --witness-image ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-leadership-witness@sha256:DIGEST \
  --worker-image ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-worker@sha256:DIGEST \
  --postgres-image docker.io/library/postgres@sha256:DIGEST \
  --valkey-image docker.io/valkey/valkey@sha256:DIGEST \
  --minio-image docker.io/minio/minio@sha256:DIGEST \
  --minio-client-image docker.io/minio/mc@sha256:DIGEST
```

The builder rejects mutable tags. Publishing is intentionally reserved for a
merged `v<pyproject version>` tag; local validation performs no provider write.
