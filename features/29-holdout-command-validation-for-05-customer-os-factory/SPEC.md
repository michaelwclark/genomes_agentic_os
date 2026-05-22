# 29 Holdout Command Validation For 05 Customer Os Factory

Validate the implemented customer OS factory from the perspective of a fresh
operator using the public CLI and example profile.

## Source Feature

- `features/05-customer-os-factory/SPEC.md`
- `features/05-customer-os-factory/HOLDOUT_QA.md`
- `customer_profiles/example-customer.yml`
- `schemas/customer-profile.schema.yml`

## Acceptance Mapping

- Customer roots contain approved customer domains, workflows, and automations.
- Customer roots do not inherit source-owner private domains.
- Updates add missing assets without overwriting local edits.
- Validation reports `core_errors` separately from `profile_warnings`.
- The source package includes an example customer profile and customer profile
  schema.
