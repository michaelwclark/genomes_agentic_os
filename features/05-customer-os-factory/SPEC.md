# Spec

Add a customer OS factory path that creates customer-specific Agentic OS roots from profile YAML.

## Commands

```bash
agentic-os customer init <customer_slug> --profile <profile.yml> --target <path>
agentic-os customer update <customer_slug> --root <path>
agentic-os customer validate --root <path>
```

## Acceptance

- Customer roots contain only approved customer domains, workflows, and automations.
- Customer roots do not inherit source-owner private domains.
- Updates add missing assets without overwriting local edits.
- Validation reports `core_errors` separately from `profile_warnings`.
- Source package includes an example customer profile and customer profile schema.
