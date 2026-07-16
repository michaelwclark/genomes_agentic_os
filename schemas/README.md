# Schemas

JSON Schema and YAML-schema documents for durable Agentic OS contracts. Runtime
code uses them to validate registries, Specs, workflows, automations, runs,
updates, customer profiles, and operator projections. A schema change should be
paired with fixture coverage and migration/compatibility guidance when it
changes an existing file contract.

Report resources use three independently versioned contracts:
`report-definition.schema.json`, `report-run.schema.json`, and
`report-artifact.schema.json`. Definitions are mutable through governed actions;
runs and artifacts are immutable evidence.

Workflow Studio uses `workflow-definition.schema.json` for the editable,
unknown-field-tolerant definition. Published versions and installed instance
pointers are immutable/readback records owned by `workflow-engine/v1`; they are
not aliases for the editable definition.
