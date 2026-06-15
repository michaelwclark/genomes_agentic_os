# 05 Customer Os Factory

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Profile Inputs](#profile-inputs)
- [Commands](#commands)
- [Generated Runtime Shape](#generated-runtime-shape)
- [Update Behavior](#update-behavior)
- [Validation](#validation)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 05 adds a customer OS factory path. It creates a customer-specific
Agentic OS root from profile YAML without copying source-owner private domains
or internal operating assumptions into the customer install.

The factory is for producing a bounded customer operating package: approved
domains, customer-selected workflows, customer-selected automations, customer
handoff assets, and reusable customer templates.

## Source And Runtime Boundaries

This repository owns the CLI behavior, schemas, examples, and templates. A
generated customer root owns the customer-facing runtime files and future local
edits.

Do not treat the generated customer root as a mirror of this source repository.
The customer root is intentionally filtered through `customer.yml`; only the
domains, workflows, automations, source systems, and approval policy described
by the profile should appear there.

## Profile Inputs

The source package includes:

- `customer_profiles/example-customer.yml`
- `schemas/customer-profile.schema.yml`
- `templates/profile/customer-os-profile.yml`

The example profile uses customer slug `acme_ops`, approved domain `support`,
default workflow `support/support/intake_triage`, and default automation
`support/support/thread_intake`.

Profiles must use lowercase slug-style identifiers. If `customer.slug` is
present, it must match the slug passed to `customer init`.

## Commands

Create a customer root from a profile:

```bash
agentic-os customer init acme_ops \
  --profile customer_profiles/example-customer.yml \
  --target /tmp/acme_os
```

Add missing assets to an existing customer root:

```bash
agentic-os customer update acme_ops --root /tmp/acme_os
```

Validate the generated customer root:

```bash
agentic-os customer validate --root /tmp/acme_os
```

The CLI prints YAML. Successful validation returns `ok: true`,
`core_errors: []`, and any non-blocking profile issues under
`profile_warnings`.

## Generated Runtime Shape

`customer init` creates root-level routing files, `customer.yml`, a customer
operating package under `customer/`, shared customer templates under
`shared_factory/05-knowledge/templates/`, and one domain folder for each
approved domain.

For the example profile, the important generated files include:

- `customer.yml`
- `customer/handoff-checklist.md`
- `customer/automation-fit-matrix.md`
- `customer/client-automation-brief.md`
- `customer/update-contract.md`
- `support/03-workflows/support/intake_triage/*`
- `support/04-automations/support/thread_intake/*`

Generated customer domains are built from the same runtime domain shape as the
main OS, but they are selected from the customer profile rather than inherited
from source-owner project history.

## Update Behavior

`customer update` is additive. It uses the same write-once behavior as the
scaffold helpers, so reruns add missing standards, templates, domains,
workflows, and automations without overwriting customer-local edits.

Use this when the source package gains new customer-safe templates or when a
customer profile changes to include additional approved domains, workflows, or
automations.

## Validation

`customer validate` separates hard runtime failures from customer profile
warnings:

- `core_errors` covers missing required customer root files and domain
  validation errors.
- `profile_warnings` covers missing optional customer profile fields, domain
  warnings, and private source-owner terms found in generated markdown or YAML.

The private-term scan is a guardrail. If `profile_warnings` mentions a private
source term, inspect the generated customer root before sharing anything with a
customer.

## Troubleshooting

If `customer init` rejects the profile, check that the command slug matches
`customer.slug` and that all customer identifiers use lowercase slug-safe text.

If validation reports missing root files, rerun `customer update` and review
the generated diff before sharing the root.

If validation reports private source terms, remove or replace that content in
the source template or customer profile, regenerate in a disposable root, and
validate again.

If customer-local edits disappear after update, treat that as a blocker. The
expected behavior is additive writes without overwriting existing customer
files.

## Source Artifacts

- Installed spec: `SPECS/05-customer-os-factory/SPEC.md`
- Installed worklog spec: `worklogs/source-features/05-customer-os-factory/SPEC.md`
- Installed worklog QA: `worklogs/source-features/05-customer-os-factory/HOLDOUT_QA.md`
- CLI: `src/genomes_agentic_os/cli.py`
- Customer factory implementation: `src/genomes_agentic_os/customer.py`
- Example profile: `customer_profiles/example-customer.yml`
- Profile schema: `schemas/customer-profile.schema.yml`
- Customer templates: `templates/customer/`
