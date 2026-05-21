# Feature Spec: Customer OS Factory

## Status

- Status: draft
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package and customer OS installs

## Problem

Genome needs one common way to create custom Agentic OS installs for customers. Today the repo can create a generic OS root, but it does not define customer profiles, customer-safe naming, packaged workflow sets, or upgrade rules across customer instances.

## Outcome

A customer OS can be generated from a profile while sharing the same core standards, templates, validation, update contract, and automation maturity model.

## Proposed Commands

```bash
agentic-os customer init <customer_slug> --profile <profile.yml> --target <path>
agentic-os customer update <customer_slug> --root <path>
agentic-os customer validate --root <path>
```

## Profile Shape

```yaml
customer:
  slug:
  display_name:
  owner:
  notion_workspace:
  approved_domains:
  source_systems:
  default_workflows:
  default_automations:
  approval_policy:
```

## Required Source Package Additions

- `profiles/` or `customer_profiles/` directory for reusable customer setup specs.
- Profile schema.
- Customer-safe template variables.
- Public/private content boundary.
- Packaged workflow and automation bundles.
- Customer update contract.

## Packaging Gap To Resolve

The current CLI works best from an editable source checkout because templates, docs, harness files, and plans live outside the Python package. Before this becomes customer-deliverable, package assets need a reliable distribution story.

Options:

- Keep customer installs source-checkout based for now.
- Move managed assets into package data and load them with `importlib.resources`.
- Add release tooling that bundles source assets into an installable archive.

## Out Of Scope

- Selling language or proposal pages.
- Customer-specific secrets.
- Customer Notion writes before connector/workspace verification.

## Acceptance Criteria

- A customer profile can create a clean OS root without private Genome-only content.
- Core update behavior remains additive and non-destructive.
- Customer-specific domains, workflows, and automations are generated from profile data.
- Validation distinguishes core OS failures from customer profile warnings.

## Validation

- Generate a temp customer OS from an example profile.
- Run `agentic-os validate`.
- Confirm no disallowed private names appear in customer-facing output.
