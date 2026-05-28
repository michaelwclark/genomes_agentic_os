# Spec Index

These specs define what the scaffold should become and what the current installable V1 already provides.

| Spec | Purpose |
| --- | --- |
| [Product Spec](product-spec.md) | Product goals, non-goals, users, object model, and V1 acceptance criteria. |
| [Architecture](architecture.md) | System layers, lifecycle, and source-of-truth rules. |
| [Data Model](data-model.md) | Optional database-backed active state model. |
| [V1 Scope](v1-scope.md) | What the first version should and should not build. |
| [CLI Spec](cli-spec.md) | Implemented V1 scaffold commands plus future command surface. |
| [Notion Scaffold Spec](notion-scaffold-spec.md) | Notion control-plane page and database model. |
| [Install Surface](install-surface.md) | Filesystem, Claude, Codex, Notion, and future runtime targets. |
| [Running OS Roadmap](running-os-roadmap.md) | Build backlog for projects, automations, context buildup, routing updates, cleanup, Notion sync, and metrics. |
| [Capability Registry](capability-registry.md) | Visible OS inventory and registry model for MCPs, skills, commands, plugins, libraries, hooks, and rules. |
| [Update Channel](update-channel.md) | Future-state channel, policy, phone-home, rollback, and customer fleet update model. |
| [Operator-Pushed Customer Updates](operator-pushed-customer-updates.md) | Simpler V1 customer update and backup model using customer-generated SSH keys, Genome billing checks, GitHub remotes, and operator-pushed releases. |
| [Harness Context Contract](harness-context-contract.md) | Shared `config.toml` plus markdown context-file contract for AGENTS, Claude adapters, routers, rules, tools, and route-read-cd-repeat behavior. |
