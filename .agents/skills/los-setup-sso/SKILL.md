---
name: los-setup-sso
description: Configure and validate tenant LOS SSO end to end, using a structured intake, VPN-backed runtime inspection, approval-gated writes, redirect proof, and Jira receipts.
---

# LOS Setup SSO

Use this skill when asked to configure, enable, repair, validate, or roll out
tenant SSO/OIDC/Okta in LOS.

## Load Order

1. Load root and LOS routing context.
2. Load `los/00-programs/los_setup_sso/{program.md,components.yml,runbook.md}`.
3. Load `los/03-workflows/engineering/los_setup_sso/{quick-reference.md,alignment-questions.md,approval-rules.md,runbook.md}`.
4. Route through `los_tenant_data`, use `los-env-shell` for VPN/kube/Django
   execution, and use `los-tenant-runtime-operation` when saving a reusable
   runtime operation.

## Procedure

1. Ask every unanswered required question in `alignment-questions.md`.
2. Save a redacted intake and decision register; never write credentials or tokens to either.
3. Validate the intake and decision-register coverage with the program scripts.
4. Read the active Jira against `jira-decision-coverage.md`; every unresolved
   security or rollout choice needs an owner-bound blocker.
5. Read the target configuration and create a compact before-state + proposed
   write set.
6. Obtain explicit approval for only the runtime/Jira mutations.
7. Apply configuration, read it back, and verify the SSO start + IdP authorization
   redirect.
8. State clearly whether JIT provisioning is enabled and whether the IdP test
   owner still needs to complete the callback.
9. Write and attach the redacted receipt to the given Jira issue.

## Safety

- Read-only work is pre-authorized in every environment and pod.
- Only mutations require approval.
- Do not store or output secrets, tokens, cookies, raw claims, or test-user PII.
- Do not infer production values from pre-prod; collect production inputs and
  perform a new read-only diff before any production mutation.
