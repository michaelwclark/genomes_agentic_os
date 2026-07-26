---
name: los-test-loan
description: Plan, generate, and approval-gate repeatable lower-environment direct synthetic LOS test-loan creation by environment, tenant, configuration reference, and target workflow task.
---

# LOS Test Loan

Use this skill when the user asks to create a repeatable QA, beta, preprod, or
other non-production LOS test loan, especially when they want the loan at a
named workflow task such as Underwriting.

1. Read `los/00-programs/los_env_shell/` and
   `los/03-workflows/engineering/test_loan_factory/`.
2. Require environment, tenant, target task or exact source application, and a
   stable idempotency key.
3. Run `los_test_loan.sh plan` first. This is read-only and may be run after the
   normal VPN/SSO/kube verification path is available.
4. If multiple configuration-reference loans match, require an exact reference
   application from the plan; do not guess. It supplies product/task/status IDs only.
5. Explain that the command creates fresh synthetic Loan, Relation,
   LoanRelation, TaskExecution, and LoanTaskAggregator rows. Never call
   `Loan.make_clone()` or reuse source relations.
6. Stop for explicit approval of the exact environment, tenant/schema,
   configuration-reference application, and direct-create write set.
7. Run `los_test_loan.sh apply` only with the confirmation token emitted by the
   plan. Production is never supported by this workflow.
8. Record the created application number and idempotency key in the run receipt.

For manual Argo use, generate a dry-run script with the wrapper's `generate`
mode or the `los-tenant-runtime-operation` generator's `test-loan-factory` subcommand.
