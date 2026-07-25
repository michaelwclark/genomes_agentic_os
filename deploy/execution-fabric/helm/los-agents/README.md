# Generic Execution Fabric worker chart

The `los-agents` directory name is retained as a compatibility address, but the
chart is deliberately a generic Genomes Agentic OS worker. It does not claim to
contain the LOSMON environment or Jira handlers. Those handlers remain in the
LOSMON adapter image and require a separate domain deployment with its own
credentials and egress policy.

The generic image validates every subscribed queue before registration and
fails closed when any accepted remote task route lacks a shipped handler. Its
default subscription is the shipped `codex_task` handler on `codex`; an image
extension must also provide the governed Codex runtime used by that handler.

One Helm release represents one durable worker identity and one scoped
bootstrap credential. `replicaCount` is therefore fixed at one. Add capacity by
installing another release with a distinct `worker.id`, `worker.bootstrapId`,
and Secret. Reusing one credential for multiple replicas would cause them to
fence each other.

The chart never creates or stores credentials. The cluster operator must
create a Kubernetes Secret and set `secrets.existingSecret` to that name.

Required Secret data:

| Value key | Default Secret key | Mounted file |
| --- | --- | --- |
| `secrets.keys.workerBootstrapToken` | `worker-bootstrap-token` | `/var/run/secrets/execution-fabric/worker-token` |

The pod exposes that mount through
`AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE`. The Python transport accepts
either the normal token environment variable or its `_FILE` counterpart, never
both. Secret contents do not enter a ConfigMap, Helm values, or pod
environment.

Use an immutable image digest. Set `worker.id`, `worker.bootstrapId`,
`worker.hostId`, queue set, capabilities, and concurrency to the exact values
bound in the control plane's worker-bootstrap credential map. The host alias
must exist in both canonical host identity and host-routing registries.

`storage.existingClaim` is mandatory and must be an RWX claim. A failed upload
is copied into that claim with an immutable SHA-256/size receipt. Replacement
pods reuse the stable workload identity, request a fresh grant bound to the
assignment's opaque recovery token, and drain a bounded batch every
`worker.spoolDrainSeconds`. Invalid or exhausted records move to quarantine
instead of retrying forever. Pending, due, and quarantined counts are included
in every worker heartbeat and are therefore visible in the central worker
snapshot.

The default NetworkPolicy permits DNS and the configured control-plane CIDRs
only. A domain image that needs GitHub, Jira, Notion, or other provider access
must ship a separate reviewed egress policy; broad Internet egress is not
silently enabled here.
