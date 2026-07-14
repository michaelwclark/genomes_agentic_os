# Spec Grooming Program

`spec_grooming` is the reusable product-development program behind
`agentic-os spec`, `/groom-spec`, the `spec-groomer` skill, and project-specific
Jira or Linear adapters. It preserves the operator's original intent, searches
for existing capability, resolves gaps and dependencies, and produces one
canonical Spec with enough context for agentic development.

It lives under `harness/shared_factory/00-programs/` because the program applies
across every domain and project. Individual Specs do **not** live here; they
move through the owning installed project's `work-items/` lifecycle.

| File | Purpose |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Program entrypoint and required operating loop. |
| [`ROUTER.md`](ROUTER.md) | Routes grooming, examples, and adapter-specific work. |
| [`CONTEXT.md`](CONTEXT.md) | Minimum context and load boundaries. |
| [`RULES.md`](RULES.md) | Intent-preservation, evidence, and write guardrails. |
| [`TOOLS.md`](TOOLS.md) | Visible commands, skills, and provider adapters. |
| [`program.md`](program.md) | Program identity, outcome, ownership, and lifecycle. |
| [`components.yml`](components.yml) | Machine-readable component inventory. |
| [`context-pack.md`](context-pack.md) | Deterministic context assembly contract. |
| [`crud.md`](crud.md) | Create/read/update/archive behavior. |
| [`documentation.md`](documentation.md) | Documentation and projection contract. |
| [`runbook.md`](runbook.md) | Operator execution sequence and recovery. |
| [`tests.md`](tests.md) | Validation and holdout expectations. |
| [`worklog.md`](worklog.md) | Program-level change history. |

Start with `AGENTS.md`, then follow `ROUTER.md` to the narrowest relevant file.
