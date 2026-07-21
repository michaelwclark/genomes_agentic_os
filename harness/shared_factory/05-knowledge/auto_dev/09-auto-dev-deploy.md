# Auto-Dev: deploy

Use `/auto-dev-deploy` to place one exact built/released artifact into one
verified environment through the project's normal deployment owner. Shared
policy defines the proof boundary; domain and project policy define the actual
environments, tools, approval gates, and commands.

## Inputs and gates

- exact artifact identity, version, digest or commit, and provenance;
- verified target environment, tenant/scope, account/cluster, and deployed
  version currently present;
- project deployment runbook, environment-access policy, health checks,
  rollback conditions, and observability route;
- required human, production, customer-impact, or change-window approval;
- terminal predecessor evidence required by project policy.

Never infer environment from the current shell, VPN, kube context, cloud
profile, branch name, or a previous run. Verify it immediately before mutation.

## Deployment behavior

1. Run the project's compact access and environment preflight.
2. Prove the deployable artifact exactly matches the approved subject.
3. Record current version and health so the before/after boundary is visible.
4. Execute the normal project-owned deployment workflow. Do not recreate its
   provider commands in this shared policy.
5. Monitor through a quiet, artifact-backed watcher when the operation is
   asynchronous.
6. Read back the provider job/result and the environment's actual version.
7. Run the configured smoke, health, migration, and behavior checks at the
   target boundary.
8. Compare observability and error signals with the defined success/rollback
   criteria.

If access expires, the target is ambiguous, the artifact differs, shared
infrastructure is unhealthy, a migration is unsafe, or rollback criteria fire,
stop and preserve evidence. Follow the project runbook and approval boundary;
do not improvise a production mutation.

## Evidence and done criteria

Record artifact identity, target, approvals, provider job, before/after version,
commands/checks, timestamps, health results, and provider/environment readback.
The stage completes only when the target reports the exact expected artifact and
the required post-deploy behavior is healthy.

A merge is not a deployment. A queued or green deployment job is not proof the
target runs the artifact, and a non-production deployment is not production
proof.
