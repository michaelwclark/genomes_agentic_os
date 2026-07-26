---
name: los-config
description: Quickly list, look up, search, compare, inspect metadata, and check freshness for local redacted LOS tenant configuration snapshots. Use this before live Django-shell access whenever tenant or environment configuration is in question.
---

# LOS Configuration Explorer

Use the local redacted snapshot registry for fast read-only configuration
analysis without VPN.

Canonical local data is under
`domains/los/00-programs/los_config/artifacts/tenant_config_snapshots/`. Treat
`runtime/objects/.../los_config/` as a compatibility path only.

The `los_config` InstanceOSProgram is the canonical owner. Read
`lib/programs/domains/los/los_config/program.md`, `components.yml`, and
`RULES.md` before changing this skill, its CLI, snapshot layout, freshness
policy, automation, or fallback routing.

## Route

1. Start with `$los-config` for configuration lookup, search, comparison,
   metadata, or freshness questions.
2. Use `$los-env-shell` only when the requested environment, tenant, key, value,
   or freshness is not covered locally.
3. Route any requested mutation to `$los-config-change`. Snapshot JSON is
   evidence only and must never be edited or replayed as an apply mechanism.

## Operations

Run `harness/bin/agentic-os-los-config`:

- `list`: list environments; add `--env` for tenants and `--tenant` for
  configuration keys.
- `lookup` or `show`: return one config's redacted `details`; add `--path`
  for a dotted path or JSON pointer.
- `search`: search config keys, JSON paths, and redacted values.
- `compare`: compare two environment/tenant locations, optionally one config
  key or nested path.
- `metadata`: return sync, release, version, source id, hashes, and
  created/updated/effective/expiry metadata.
- `freshness`: evaluate `configmeta.json` timestamps against a maximum age.

## Examples

```bash
harness/bin/agentic-os-los-config list
harness/bin/agentic-os-los-config list --env preprod --tenant navyfederal --match email
harness/bin/agentic-os-los-config lookup --env preprod --tenant navyfederal --config email_config
harness/bin/agentic-os-los-config lookup --env preprod --tenant navyfederal --config email_config --path sender.name
harness/bin/agentic-os-los-config search laserpro --env preprod --tenant navyfederal --limit 25
harness/bin/agentic-os-los-config compare --left-env preprod --left-tenant navyfederal --right-env prod --right-tenant navyfederal --config email_config
harness/bin/agentic-os-los-config metadata --env preprod --tenant navyfederal --config email_config
harness/bin/agentic-os-los-config freshness --max-age-hours 30
```

## Evidence Contract

- Read each involved environment's `configmeta.json` and report its
  `last_successful_sync_at` with conclusions.
- Treat missing, invalid, or stale coverage as a reason for a bounded live
  read-only fallback, not as proof of configuration state.
- Results are redacted. A redacted value cannot answer a secret-value question.
- Comparisons identify drift; they do not prove that either side is correct.
- Never mutate LOS, Kubernetes, Jira, or external systems from this skill.
