---
name: los-tenant-data
description: Route and operate LOS tenant configuration, rules-engine, tenant runtime investigation, governed data-change, and lower-environment test-object work through one local-first program.
---

# LOS Tenant Data

1. Read `lib/programs/domains/los/los_tenant_data/ROUTER.md`, `RULES.md`,
   `TOOLS.md`, and `components.yml`.
2. Select one workflow intent: configuration research, rules-engine research,
   runtime investigation, governed change, or test-object creation.
3. Use current canonical local configuration or rules-engine evidence first.
4. Use `$los-env-shell` only for stale, incomplete, selector-sensitive, or
   runtime-only evidence and approved refresh.
5. Search `$los-tenant-runtime-operation` before creating a new operation.
6. Default live work to `inspect`; produce a `plan` and require explicit
   approval before `apply`.
7. Store a bounded receipt with environment, tenant, source, mode, outcome, and
   verification status.
