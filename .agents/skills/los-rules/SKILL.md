---
name: los-rules
description: Analyze local redacted LOS rules-engine snapshots with fast list, lookup, search, compare, metadata, and freshness operations. Use for tenant or environment rules questions before opening a live LOS shell.
---

# LOS Rules Explorer

Canonical local data is under
`domains/los/00-programs/los_rules_engine/artifacts/rules_engine_snapshots/`.
Treat `runtime/objects/.../los_rules_engine/` as a compatibility path only.

1. Read `lib/programs/domains/los/los_rules_engine/` before changing behavior.
2. Use `harness/bin/agentic-os-los-rules` for local analysis.
3. Check `rulesmeta.json` and report `last_successful_sync_at` for every involved environment.
4. Treat missing, partial, or older-than-14-hour coverage as a reason for a bounded `$los-env-shell` read.
5. Treat redacted values as unknown and comparisons as drift evidence, not correctness proof.
6. Never upload, approve, execute, or mutate rules from this skill.

## Operations

```bash
harness/bin/agentic-os-los-rules list --env preprod --tenant navyfederal
harness/bin/agentic-os-los-rules lookup --env preprod --tenant navyfederal --rule WorkflowNextStep --path data.table
harness/bin/agentic-os-los-rules search decline --env preprod --tenant navyfederal --limit 25
harness/bin/agentic-os-los-rules compare --left-env preprod --left-tenant navyfederal --right-env prod --right-tenant navyfederal --rule WorkflowNextStep
harness/bin/agentic-os-los-rules metadata --env preprod --tenant navyfederal --rule WorkflowNextStep
harness/bin/agentic-os-los-rules freshness --max-age-hours 14 --fail-stale
```
