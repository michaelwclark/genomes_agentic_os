# Investigation

- Generic `create_domain`, `create_workflow`, and `create_automation` call the default OS initializer, so customer generation needs a customer-specific scaffold path.
- Customer validation cannot use the full default `validate` command because customer roots intentionally do not include Genome's personal default domains.
- Existing customer templates are public-safe when rendered with customer profile values.
