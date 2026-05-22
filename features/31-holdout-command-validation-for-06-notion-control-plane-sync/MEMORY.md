# Memory

Feature 06 holdout validation should assert both guardrail and idempotency:
apply without a verified workspace exits non-zero, apply with `Genome's Notion`
writes `.notion-sync/mapping.yml`, and a later dry run reports all no-op actions
when source files are unchanged.
