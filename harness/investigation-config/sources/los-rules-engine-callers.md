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
  touched_paths:
    - los/services/vendors/rule_engine.py
    - los/services/managers/rule_engine_manager.py
    - los/services/views.py
    - los/requests/api/views.py
    - los/requests/managers/**
    - los/requests/validators.py
    - los/offer_engine/**
    - los/origination/strategies/rate.py
    - los/backoffice/executor.py
    - los/backoffice/managers/products.py
    - los/backoffice/bo_tasks/**
    - los/workflows/**
    - los/spreading/**
    - los/rich_text_documents/**
    - los/health/checks/rules_engine_health.py
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
  - canonical source revision, module, and symbol
  - selected kit contract and snapshot freshness/coverage
  - known validation findings or explicit insufficiency
  - tenant/environment/source-evidence provenance for every conclusion
failure:
  stale_or_incomplete_snapshot: return_unknown_or_insufficient_evidence
---

# LOS Rules Engine caller context

When a matched Django caller changes, this policy selects a Rules Engine
*candidate* only. It is not a loaded kit. The resolver may report `loaded`
only after the declared catalog identifies one ready rulebook and it hashes all
five concrete files: `contract.yml`, `dictionary.yml`, `checks.yml`,
`coverage.yml`, and `redundancy.yml`. Those files must agree on their v1
identity/entity/readiness headers, and a compact known-findings receipt must be
available (an empty verified list is valid). Until then it records
`kit-unavailable` or `insufficient-evidence` rather than treating this Markdown
policy as kit evidence.

Use redacted local snapshots first when a local snapshot registry exists. The
frozen receipt records only compact registry hashes, tenant/rule coverage,
timestamp/freshness, and any declared compact findings envelope. Missing,
stale, malformed, or incomplete snapshot evidence is an explicit limitation,
not a healthy result and not authority to read or mutate a live tenant. Daily
validation remains problem-only: do not emit healthy-case noise, and keep
unconfirmed unused/redundancy ideas separate from defects.

The program is an evidence producer for Project Rubicon. Do not create or
mutate Control Plane lifecycle, queue, lease, fence, cursor, idempotency, or
raw-data records here.
