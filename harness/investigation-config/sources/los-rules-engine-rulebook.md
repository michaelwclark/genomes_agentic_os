---
schema_version: 1
id: los-rules-engine-kits
kind: source
title: Snapshot-backed LOS Rules Engine validation kits
priority: 18
applies_to:
  domains:
    - los
  projects:
    - los_app_los_django
  subjects:
    - rules-engine
    - rulebook
authority:
  class: canonical Django contract plus redacted Rules Engine snapshots
  source_contract: los/services/vendors/rule_engine.py
freshness:
  mode: snapshot_age_and_coverage_required
  max_age_hours: 72
requirements:
  program: lib/programs/domains/los/los_rules_engine
  rules_engine_context:
    catalog_ref: lib/programs/domains/los/los_rules_engine/config/rulebook_kits/catalog.yml
    snapshot_root_ref: domains/los/00-programs/los_rules_engine/artifacts/rules_engine_snapshots
    required_kit_files:
      - contract.yml
      - dictionary.yml
      - checks.yml
      - coverage.yml
      - redundancy.yml
    max_age_hours: 72
  validation_mode: problem_only_high_confidence
  live_mutation: prohibited
tools:
  - agentic-os-los-rules
  - agentic-os detective
evidence:
  - exact rulebook identity or unmapped-search evidence
  - selected kit contract and snapshot freshness/coverage
  - known validation findings or explicit insufficiency
  - tenant/environment/source-evidence provenance for every conclusion
failure:
  stale_or_incomplete_snapshot: return_unknown_or_insufficient_evidence
---

# LOS Rules Engine rulebook context

When a work item is declared as `rules-engine` or `rulebook`, pass the exact
rulebook identity with `--rulebook-id` to resolve it through the declared local
catalog. A subject alone is insufficient to choose a kit. The resolver records
`kit-unavailable` when the catalog or five concrete kit artifacts are absent,
and `insufficient-evidence` when identity, coverage, freshness, or another
required local evidence input is not usable. It must never claim that this
policy file itself loaded a kit. If the identity is not mapped, preserve the
search evidence as `unmapped`; never infer that the rulebook is unused.

`loaded` also requires every concrete kit document to agree on the v1 kit ID,
`rulebook` entity kind, and `ready` completion state, plus an available compact
known-findings receipt (an independently verified empty findings list is
valid). A missing or undeclared findings receipt is `insufficient-evidence`.

Use the same snapshot-first, problem-only, privacy-safe evidence contract as
the caller route. Conversational answers must identify tenant, environment,
snapshot timestamp/freshness, source evidence, and uncertainty; return
unknown/insufficient evidence when coverage is incomplete.
