# Investigation

Feature 05 is implemented through the `agentic-os customer` command group in
`src/genomes_agentic_os/cli.py`, backed by `src/genomes_agentic_os/customer.py`.

The source package already contains the profile input needed for holdout
validation:

- `customer_profiles/example-customer.yml`
- `schemas/customer-profile.schema.yml`
- `templates/customer/*`
- `templates/profile/customer-os-profile.yml`

The existing test suite includes customer factory coverage for public customer
root generation, additive update behavior, local edit preservation, validation
output, and private-name filtering. The holdout still runs the behavior through
the installed CLI surface rather than relying only on tests.
