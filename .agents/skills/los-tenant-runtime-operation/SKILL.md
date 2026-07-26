---
name: los-tenant-runtime-operation
description: Reuse or create production-safe LOS Tenant Runtime Operations for inspection, dry-run planning, tenant resolution, and explicitly authorized data changes, independent of whether execution uses Argo, kubectl, or another approved shell transport.
---

# LOS Tenant Runtime Operation

## Workflow

1. Route through `lib/programs/domains/los/los_tenant_data/`, then load
   `domains/los/00-programs/los_env_shell/` and read its `RULES.md`,
   `TOOLS.md`, and `tenant_runtime_operations/tenant_runtime_operations.json` before
   drafting. Search likely matching family READMEs under `tenant_runtime_operations/`.
2. Reuse an existing script when one fits the request. Lightly adapt environment-specific health URLs or documented parameters instead of rewriting the script.
3. If an existing script is close but not exact, fork it into a new variant instead of starting from scratch. As a rule of thumb, when a script is roughly 70% or more applicable, preserve the original, copy it into the same script family or a clearly named sibling folder, document what changed, add the variant to `tenant_runtime_operations.json`, and create/update its Notion page.
4. If no reusable or close-match script exists, decide whether the request is generic or one-off. If it is tied to a specific loan, tenant, application, task id, customer incident, or exact data repair, ask Genome whether to create a generic reusable version before saving it in the repository.
5. Save reusable scripts only in `/Users/genome/agentic_os/domains/los/00-programs/los_env_shell/tenant_runtime_operations/<script_id>/` with `README.md`, the script file, and an outputs folder. The README must include an explicit `Context` section. Register the family in `tenant_runtime_operations.json` and the program `TOOLS.md` in the same change. Add `EXAMPLE.md` when the script is destructive, complex, multi-step, or has non-obvious output interpretation.
6. Capture outputs. When Genome pastes runtime-operation output back, or when you run an operation through an approved shell transport, save the output under the matching `*_outputs/<YYYY_MM_DD_context>/` folder as `output.jsonl` when structured or `output.txt` otherwise, with a short output `README.md`.
7. Fetch the current prod health metadata before drafting production scripts. For Navy Federal production, use `https://navyfederal.los.lenderscooperative.com/api/health_check` and capture branch, build number, and commit.
8. Inspect the LOS Django source at `/Users/genome/projects/los/app/los-app-los-django` against that prod commit when available. Keep the source checkout read-only unless the user explicitly asks for code changes.
9. Generate new Tenant Runtime Operations with `scripts/build_tenant_runtime_operation.py` when a repository script or template does not already fit. The generated script must start with the fixed warning/DD/logging preamble, with no comments or text before it.
10. Default every script to read-only investigation. If the user asks for a data update, include a dry-run path, explicit target counts, before/after prints, and stop for user approval before producing a mutation-enabled final script.
11. Resolve tenants from live prod tenant tables, not stale guesses. Use the tenant-map task when the prompt contains a human customer name such as "Penn Community", "Lafayette", "LFCU", or "NFCU".
12. Keep stdout thin. Assume pasted output may be truncated; print counts, compact summaries, top candidates, and final conclusions by default. Do not print full querysets, full tenant maps, full vendor payloads, full `details` JSON, stack traces, or more than a small capped row sample unless the user explicitly asks for verbose/full output.

## Operating Contract

- Ownership: Agentic OS root skill for LOS production Django script drafting, with LOS Django project context loaded when code/model details are needed.
- Context routing: start at `/Users/genome/agentic_os`, route through `los/`, and load `los/02-projects/los_app_los_django` before inspecting source code.
- Validation: run the skill validator, `py_compile` for `scripts/build_tenant_runtime_operation.py`, and compile-check generated `exec("""...""")` bodies before handoff.
- Projection: save reusable scripts and output history under `/Users/genome/agentic_os/domains/los/00-programs/los_env_shell/tenant_runtime_operations/`. Write temporary one-off artifacts under the routed LOS project `artifacts/` folder only when the user has not approved saving a reusable repository version. Do not write to Notion for this skill by default.

## LOS Tenant Runtime Operations Repository

Repository root:

```text
/Users/genome/agentic_os/domains/los/00-programs/los_env_shell/tenant_runtime_operations
```

Manifest:

```text
/Users/genome/agentic_os/domains/los/00-programs/los_env_shell/tenant_runtime_operations/tenant_runtime_operations.json
```

Each reusable script folder should contain:

```text
README.md
<script_name>.py
<script_name>_outputs/
EXAMPLE.md  # when complex, destructive, multi-step, or interpretation-heavy
```

Script READMEs must explain:

- what the script does;
- the operational context and when to choose this script;
- what it does not do;
- whether it is read-only or destructive;
- required environment/build/tenant/loan inputs;
- how to execute it through approved environment access, including Argo when applicable;
- how to interpret the important output labels;
- where to save future outputs.

Output folders should contain:

```text
README.md
output.jsonl  # preferred for structured label/payload output
output.txt    # fallback for unstructured output
```

When saving pasted output, preserve the script-emitted labels and payloads. Add capture metadata such as environment, build, commit, date, and short interpretation in the output folder README.

## Close-Match Variant Rule

When repository search finds a script that is close but not exact:

- Prefer adapting it over writing a new script from a blank page.
- Preserve the original script unchanged.
- If the change is a minor environment or input adjustment, save the variant in the same script folder with a clear filename.
- If the change broadens the tool into a reusable pattern, create a sibling folder with a generic script name.
- Update `README.md` with "Based on" and "What changed" notes.
- Add or update `EXAMPLE.md` when output interpretation changes.
- Add the variant to `tenant_runtime_operations.json`.
- Add or update the matching row in the program `TOOLS.md`.
- Create or update the matching Notion page named `LOS Tenant Runtime Operation - ${script name}`.

## Required Preamble

Every generated script must begin exactly with:

```python
PYTHONWARNINGS=ignore DD_TRACE_ENABLED=false DD_TRACE_STARTUP_LOGS=false python manage.py shell -i python

exec("""
import logging

for name in [
    "botocore",
    "boto3",
    "s3transfer",
    "urllib3",
    "ddtrace",
    "ddtrace.internal",
]:
    logging.getLogger(name).setLevel(logging.WARNING)

logging.getLogger().setLevel(logging.WARNING)
print("quieted noisy loggers")
""")
```

Put the task-specific code in a second `exec("""...""")` block after the preamble.

## Generator

Use:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py tenant-map \
  --query "Penn Community" \
  --query "Lafayette" \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/los-prod-tenant-map.py
```

Default tenant-map output prints `tenant_count`, compact matches for requested queries, and omits the full map. Use `--full --limit N` only when a compact full list is needed.

Use the servicing funds investigation template for discrepancies between Loan Details and transaction history:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py servicing-funds-investigation \
  --tenant "Lafayette Federal Credit Union" \
  --loan-number 14805662293 \
  --application-number 2025102901 \
  --business-name "Work With Your Handz, LLC" \
  --expected-ui-funds-available 87111.53 \
  --expected-ui-principal-balance 112704.10 \
  --around-date 2026-06-03 \
  --max-payment-rows 8 \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/lfcu-funds-available-14805662293.py
```

Use the decline process investigation template to compare stuck decline-status loans against a completed control loan:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py decline-process-investigation \
  --tenant "Navy Federal" \
  --application "73271982111:Ysleta Mission Gift Shop" \
  --application "73271702104:Seabreeze Hollow Farm LLC" \
  --application "73271417353:Touch Down LLC control-completed" \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/nfcu-decline-process-investigation.py
```

This template defaults to one single-line JSON summary per application plus a single-line overall comparison. Use `--include-details` only for a second pass that needs capped task, aggregator, and audit sections.

Use the decline process repair-plan template only after an investigation has confirmed exact stuck candidates. It is dry-run-only and prints whether each target is blocked on hard-pull completion or eligible for a separate approval-gated terminal backfill:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py decline-process-repair-plan \
  --tenant "Navy Federal" \
  --application "73271982111:Ysleta Mission Gift Shop" \
  --application "73271702104:Seabreeze Hollow Farm LLC" \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/nfcu-decline-process-repair-plan.py
```

Do not convert the repair-plan output into a mutation script until the user explicitly approves the exact target IDs and proposed write set.

Use the decline process root-cause validation template before writing a bug ticket when the suspected cause is an accepted decline task whose next step is blocked by the decline-in-progress guard. It is read-only: it reconstructs the queued next-task executor, asks the rules engine for the next response, computes the guard decision, and prints existing credit-bureau task evidence without creating tasks:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py decline-process-root-cause-validation \
  --tenant "Navy Federal" \
  --application "73271982111:Ysleta Mission Gift Shop" \
  --application "73271702104:Seabreeze Hollow Farm LLC" \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/nfcu-decline-root-cause-validation.py
```

The generator can print to stdout or write with `--output`. Generated scripts are intended to be pasted into an Argo terminal for a prod Django pod.

Use the queue depth check template when production OOMs may be related to a backed-up queue. It is read-only: it prints current health metadata, Celery broker queue depth from SQS or Redis settings, and `TerminatorTaskQueue` backlog counts without dumping task payloads:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py queue-depth-check \
  --full-threshold 1000 \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/los-prod-queue-depth-check.py
```

Use `--queue <name>` when the incident names a specific Celery/SQS queue, and repeat `--terminator-status <status>` if a nonstandard Terminator status should count as open/backlogged.

Use the terminator schema check template when a production tenant may be missing the `terminator_terminatortaskqueuesettings` table after a `django-terminator` upgrade. It is read-only: it resolves the tenant, checks table presence, reports recent `terminator` migration rows, and can sweep production tenants for the same table gap:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py terminator-schema-check \
  --tenant "desertfinancial" \
  --sweep-production \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/los-prod-terminator-schema-check.py
```

If the target table is missing, rerun the script after the approved tenant migration has been applied. Do not convert this into a mutation or migration-running script without explicit operator approval for the exact tenant/schema.

Use the approval worksheet investigation template when a boarded/funded loan is reported as missing the Approval Worksheet / underwriting-settlement sheet, especially when Slack or Jira says LOS still shows Doc Prep:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py approval-worksheet-investigation \
  --tenant "Encore Bank" \
  --application-number 21538122706 \
  --business-name "H2A Technologies, Inc." \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/encore-approval-worksheet-21538122706-investigation.py
```

This template is read-only. By default it prints only tenant/schema, loan/current-task state, counts, classification hints, and the next command to run. It intentionally omits task rows, aggregators, full `details`, full core-integration payloads, and document file URLs. Add `--include-details` only after the compact classification proves the extra rows are needed.

Use the approval worksheet repair-plan template only after the investigation confirms the target loan and state mismatch. It remains read-only and dry-run-only: it prints whether the case is a missing worksheet regeneration candidate or a broader LOS/Ventures workflow-state mismatch.

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py approval-worksheet-repair-plan \
  --tenant "Encore Bank" \
  --application-number 21538122706 \
  --business-name "H2A Technologies, Inc." \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/encore-approval-worksheet-21538122706-repair-plan.py
```

Do not convert the repair-plan output into a mutation script until the user explicitly approves the exact tenant/schema, loan id, task id, and proposed write set.

Use the Doc Prep progression investigation template when the Approval Worksheet investigation proves the loan is still active at `DOC_PREP` and has not reached closing signed-documents:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py doc-prep-progression-investigation \
  --tenant "Encore Bank" \
  --application-number 21538122706 \
  --task-id 1259 \
  --business-name "H2A Technologies, Inc." \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/encore-doc-prep-progression-21538122706.py
```

This template is read-only. It checks the current Doc Prep task, visible task actions, Doc Prep validation blockers, condition counts, open condition service requests, relevant latest tasks, and selected core-integration response step summaries. It does not run `send_to_next_level`, accept, submit, regenerate documents, or update workflow state.

Use the Doc Prep closing-date repair-plan template after the progression investigation shows `closing_date_not_past` is the active blocker:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py doc-prep-closing-date-repair-plan \
  --tenant "Encore Bank" \
  --application-number 21538122706 \
  --task-id 1259 \
  --business-name "H2A Technologies, Inc." \
  --proposed-closing-date YYYY-MM-DD \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/encore-doc-prep-closing-date-21538122706-repair-plan.py
```

This template is read-only and dry-run-only. Without `--proposed-closing-date`, it prints the stale closing-date evidence and asks for a business-approved current/future date. With a proposed date, it validates the date through `LoanValidator.validate_closing_date`, calculates projected dependent dates in memory, and prints the approval-gated write set that a later mutation script would need to recheck.

Use the SBA number disambiguation template when a screenshot or support note gives an `SBA Number` and it is unclear whether that value is an SBA/ETRAN identifier or an LOS boarded loan number:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py sba-number-disambiguation \
  --tenant "Encore Bank" \
  --application-number 21538122706 \
  --sba-number 8091029102 \
  --business-name "H2A Technologies, Inc." \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/encore-sba-number-disambiguation-21538122706.py
```

This template is read-only. It searches direct loan identifiers (`application_number`, `loan_number`, `sba_number`, and `sba_loan_app_number`) and prints whether the SBA number belongs to the same Doc Prep application or a separate LOS loan-number match, plus compact worksheet/boarding/closing terminal counts.

Use the ETRAN status provenance template after disambiguation proves the SBA number belongs to the same Doc Prep application and the question becomes how `sba_loan_status = Funded` was written:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py etran-status-provenance \
  --tenant "Encore Bank" \
  --application-number 21538122706 \
  --sba-number 8091029102 \
  --business-name "H2A Technologies, Inc." \
  --health-url https://navyfederal.los.lenderscooperative.com/api/health_check \
  --output /tmp/encore-etran-status-provenance-21538122706.py
```

This template is read-only. It prints compact loan audit rows touching SBA/ETRAN fields, relevant SBA/ETRAN task rows, and loan-linked interface-log rows so the operator can identify whether the funded status came from manual ETRAN details capture, ETRAN submission/response, score-check response, or a later status refresh.

Use the guarded queue purge template only when an operator explicitly approves dropping queued Celery broker work in a non-prod or approved production environment. It targets exactly one broker queue, prints before/after counts, and does not touch `TerminatorTaskQueue` database rows:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py queue-purge \
  --environment-label qa \
  --queue celery \
  --output /tmp/qa-celery-queue-purge-dry-run.py
```

The default script is dry-run-only. To generate an execution-enabled script, include `--enable-purge --confirmation PURGE_QA_CELERY_QUEUE` after the exact queue name has been confirmed. Do not use this for production without a fresh approval and environment-specific confirmation token.

Use the test loan factory template when a QA, beta, preprod, or other
non-production tenant needs a repeatable clone of a loan already at a requested
workflow task:

```bash
python3 .agents/skills/los-tenant-runtime-operation/scripts/build_tenant_runtime_operation.py test-loan-factory \
  --environment-label qa-multi \
  --tenant qa-testbank \
  --target-task UNDERWRITING \
  --idempotency-key QA-UNDERWRITING-001 \
  --output /tmp/qa-testbank-underwriting.py
```

The default script is read-only and prints bounded source candidates. If more
than one source matches, regenerate with `--source-application`. Generate an
apply-enabled script only after approving the exact environment, tenant/schema,
source application, and clone write set; add `--enable-create --confirmation
CREATE_QA_MULTI_QA_TESTBANK_TEST_LOAN`. Production is refused. The template
reuses `Loan.make_clone()` and validates task state instead of forcing workflow
transitions.

## Output Budget

Treat Argo output as a scarce debugging channel.

- Print health metadata as `{env, build, branch, commit, status}` only.
- Print queue data as compact depth counts, age buckets, and capped top rows only; do not print task payloads, broker URLs, credentials, or full SQS queue attributes.
- For queue purge scripts, print only the targeted queue name, broker scheme, before/after counts, mutation flag, and confirmation status.
- Print tenant data as `{name, schema_name, domains[:2], in_production, is_ready, match_score}`.
- Print no more than 3 tenant matches per query unless `--full` is set.
- Print no more than `--max-payment-rows` transaction rows; default to 8.
- Print essential payment fields only: dates, type, amount, principal, interest, trans code, and balance candidates.
- Print verbose identifiers, detail keys, and full tenant maps only behind explicit flags such as `--verbose` or `--full`.
- When `--include-ventures-live` is used, still print compact vendor rows only; do not dump the raw vendor payload.
- End with enough counts and deltas to classify the issue without needing the omitted raw rows.

## Tenant Mapping

The generated tenant-map script switches to the public schema and reads `Organization` plus primary/custom `Domain` rows. By default it prints only compact matches and counts; it does not dump every tenant.

When resolving a human name, the script scores matches against:

- `Organization.name`
- `Organization.schema_name`
- `Organization.code`
- related domain names
- aliases from `references/tenant-aliases.json`

If no confident match exists, or multiple tenants tie, the script prints candidate rows and stops instead of guessing.

## LOS Servicing Funds Pattern

Read `references/los-servicing-funds-available.md` when the prompt mentions funds available, principal balance, payment history, draw requests, Ventures, LFCU, or borrower loan details.

For Loan Details discrepancies, compare:

- `LoanValidation.current_approval_amount` or `initial_approved_amount`
- `LoanValidation.outstanding_balance`
- `LoanValidation.total_undisbursed_amount`
- `LoanValidation.funds_available`
- local `PaymentHistory` rows for the same `loan` or `loan_number`
- optional Ventures live transactions only when explicitly enabled

The expected basic line-of-credit arithmetic is:

```python
expected_funds_available = approved_amount_basis - outstanding_balance
```

If `funds_available` equals `approved_amount_basis - previous_balance`, the stored field is likely stale relative to a principal payment. If `outstanding_balance` is stale too, continue tracing the upstream import/sync source before calling it a UI bug.
