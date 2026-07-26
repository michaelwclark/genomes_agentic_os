---
name: los-env-shell
description: Verify or refresh missing, stale, incomplete, redacted, selector-specific, or runtime-only LOS evidence through Kubernetes/Django shells after snapshot-first analysis. Read-only access is pre-authorized in every environment/pod; prefer deploy/los-backend and gate only mutations.
---

# LOS Environment Shell

Use this skill to verify and operate LOS environment shells. The canonical
program is `los_env_shell`; `los_prod_shell` is the legacy production alias.
All environments follow the `los_<env>_shell` naming convention and use the
same helper and reusable-script repository.

## Load Order

1. Start from `/Users/genome/agentic_os`.
2. Load the root context: `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`.
3. Load the LOS context: `los/ROUTER.md`, `los/CONTEXT.md`, `los/RULES.md`, `los/TOOLS.md`.
4. Load this program context:
   - `los/00-programs/los_env_shell/program.md`
   - `los/00-programs/los_env_shell/components.yml`
   - `los/00-programs/los_env_shell/RULES.md`
   - `los/00-programs/los_env_shell/runbook.md`
   - `los/00-programs/los_env_shell/tests.md`
5. If drafting or selecting a Django shell script, load
   `los/00-programs/los_env_shell/tenant_runtime_operations/tenant_runtime_operations.json`,
   the likely family README, program `TOOLS.md`, and
   `.agents/skills/los-tenant-runtime-operation/SKILL.md`.
6. For any tenant/environment configuration question, load the `los_config`
   program and `$los-config` first. Continue here only when local evidence is
   insufficient.
7. For any tenant/environment rules-engine question, load the
   `los_rules_engine` program and `$los-rules` first. Continue here only when
   local evidence is missing, stale, incomplete, redacted, or runtime-only.

## Environment Naming

- `los_prod_shell` is the production shell.
- `los_multi_shell` is the shared multi account/cluster shell context.
- `los_qa_multi_shell` is the QA multi shell when using the local `los-qa-multi` profile/context.
- `los_beta_multi_shell` is the beta multi shell when using the local `los-beta-multi` profile/context.
- Other environments use `los_<env>_shell` and the helper convention:
  `AWS_PROFILE=los-<env>`, `KUBE_CONTEXT=los-<env>`, unless overridden.

Known local environments:

| Env | AWS profile | Kube context | Status |
| --- | --- | --- | --- |
| `prod` | `los-prod` | `arn:aws:eks:us-east-2:216426985617:cluster/eks-cluster-prod` | Verified kube access |
| `multi` | `los-multi` | `los-multi` | Configured locally; VPN required before kube use |
| `qa-multi` | `los-qa-multi` | `los-qa-multi` | Configured locally; VPN required before kube use |
| `beta-multi` | `los-beta-multi` | `los-beta-multi` | Configured locally; VPN required before kube use |

## Procedure

1. Identify the environment. If the user does not name one, assume `prod` only
   when the request clearly says production; otherwise ask for the target env.
2. For configuration reads or comparisons, run `$los-config` first and continue
   only when it reports missing, stale, incomplete, redacted, selector-specific,
   or runtime-only evidence. Do not edit or replay snapshot files.
   For rules-engine reads or comparisons, use `$los-rules` and `rulesmeta.json`
   under the same snapshot-first boundary.
3. Confirm the approved VPN is connected before any `los-prod` or
   Kubernetes-backed shell access. This applies to `verify`, `noop`, `run`,
   `interactive`, raw `kubectl`, and Django shell investigation paths. AWS SSO
   or kube credentials are not sufficient without VPN connectivity.
4. Verify access:

   ```bash
   los/00-programs/los_env_shell/scripts/los_env_shell.sh <env> verify
   ```

   If AWS SSO has expired, run:

   ```bash
   aws sso login --profile los-<env>
   ```

   For production, that is:

   ```bash
   aws sso login --profile los-prod
   ```

5. If VPN status is unknown, or verify reports that kube is not reachable,
   prompt the user to connect the approved AWS VPN, then retry after they
   confirm. Do not treat the cluster, AWS account, RBAC, or shell target as
   broken until VPN connectivity has been confirmed.
6. Choose a shell execution target only when the snapshot is missing, stale,
   redacted beyond the question, or lacks runtime-only evidence. Read-only
   inspection is pre-authorized in every environment and pod; prefer
   `deploy/los-backend` for stability, then another Django-capable target. Keep
   output bounded and observe pod health because an earlier production Django
   shell startup OOMKilled a serving pod.
7. Run the read-only no-op check:

   ```bash
   TARGET=deploy/los-backend \
     los/00-programs/los_env_shell/scripts/los_env_shell.sh <env> noop
   ```

   Expected marker format: `los_<env>_shell_ok`, with hyphens converted to
   underscores.

8. For read-only investigation, search the canonical reusable-script manifest
   and family READMEs first. Reuse or generate the script with
   `los-tenant-runtime-operation`, then run it through the helper:

   ```bash
   TARGET=deploy/los-backend \
     los/00-programs/los_env_shell/scripts/los_env_shell.sh <env> run /path/to/script.py
   ```

9. Capture material output. For reusable scripts, save output under the matching
   `/Users/genome/agentic_os/domains/los/00-programs/los_env_shell/tenant_runtime_operations/<script_id>/<script_id>_outputs/`
   folder. For one-off evidence, save the command, env, target, result marker,
   and concise interpretation in the active LOS run log or work item artifact.
10. Report only the blocker-grade result and receipt path. Do not paste secrets,
   full customer payloads, full querysets, or large logs into chat.

## RCA And Grooming Consumers

For `#los_prod_warriors` RCA creation or Jira technical grooming, this shell
path is the required production evidence step. Require tenant/client and
application/loan/service-request/task identifiers before running a prod script.
If identifiers are missing, ask in Slack for the tenant and app/loan/SR id, then
record the answer for the script input. Script output must be read-only,
bounded, and redacted before any Jira add-on.

## Safety Contract

- The approved VPN is required before `los-prod` or any Kubernetes-backed shell
  access. If VPN status is unknown, ask the user to connect VPN before running
  kube or shell commands.
- `verify` is the safe first command for every environment.
- Governed snapshot automations may use bounded `wait-vpn`; timeout defers and
  does not excuse subsequent SSO, kube, or service failures.
- Local snapshots are redacted, read-only evidence and may be stale. Treat
  `<env>/configmeta.json` as authoritative for sync/coverage metadata, not as
  proof that the source has not changed since.
- Read-only `noop` and `run` use is pre-authorized in every environment and
  pod. Prefer `deploy/los-backend` for stability; another Django-capable target
  is allowed when necessary.
- Treat interactive shells as potentially mutating; they require
  `LOS_SHELL_OPERATION=mutation ALLOW_LOS_SHELL_MUTATION=1` after approval.
- Default to bounded, redacted read-only investigation.
- Any mutation, repair, task rerun, data backfill, migration, queue action, or
  external write requires explicit user approval for the exact environment,
  target, and write set after a dry-run or read-only evidence pass.
- Do not store AWS credentials, session tokens, customer payloads, presigned
  URLs, or secret-like values in docs, scripts, logs, Notion, Jira, GitHub,
  Slack, or chat.
- Keep stdout compact: print counts, IDs needed for follow-up, capped samples,
  and conclusions.

## Common Commands

Verify production shell access:

```bash
los/00-programs/los_env_shell/scripts/los_env_shell.sh prod verify
```

Verify QA multi shell access:

```bash
los/00-programs/los_env_shell/scripts/los_env_shell.sh qa-multi verify
```

Verify beta multi shell access:

```bash
los/00-programs/los_env_shell/scripts/los_env_shell.sh beta-multi verify
```

No-op shell check:

```bash
TARGET=deploy/los-backend \
  los/00-programs/los_env_shell/scripts/los_env_shell.sh prod noop
```

Run an investigation script and keep a receipt:

```bash
set -o pipefail
TARGET=deploy/los-backend \
  los/00-programs/los_env_shell/scripts/los_env_shell.sh prod run /path/to/script.py 2>&1 | tee /path/to/output.txt
```

Open an interactive shell in a user terminal:

```bash
LOS_SHELL_OPERATION=mutation ALLOW_LOS_SHELL_MUTATION=1 TARGET=deploy/los-backend \
  los/00-programs/los_env_shell/scripts/los_env_shell.sh prod interactive
```
