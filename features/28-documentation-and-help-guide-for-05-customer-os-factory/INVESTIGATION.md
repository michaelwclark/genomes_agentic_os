# Investigation

Feature 05 is exposed by `agentic-os customer` subcommands in
`src/genomes_agentic_os/cli.py` and implemented in
`src/genomes_agentic_os/customer.py`.

The guide content is grounded in these source artifacts:

- `features/05-customer-os-factory/SPEC.md`
- `features/05-customer-os-factory/HOLDOUT_QA.md`
- `customer_profiles/example-customer.yml`
- `schemas/customer-profile.schema.yml`
- `templates/customer/`
- `templates/profile/customer-os-profile.yml`

The implementation uses write-once scaffold helpers for customer assets, so the
guide can state that updates add missing files without overwriting existing
customer-local edits.
