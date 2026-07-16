# Harness Registries

Registries are version-controlled defaults consumed by harness helpers and the
Python capability layer. They describe available behavior; mutable runtime
state and customer-specific values belong in the installed OS.

| Registry | Purpose | Primary consumer |
| --- | --- | --- |
| `first-class-resources.json` (installed, generated) | Atomic, versioned index of Automations, Programs, Workflows, Rules, Reports, Skills, and Commands across system, domain, and project scopes. Refresh with `agentic-os resource-registry refresh`; normal reads never scan the tree. | Command Center and other latency-sensitive operator surfaces |
| [`alerts.yml`](alerts.yml) | Alert thresholds, quiet hours, sounds, and source policies. | `agentic-os-notify` and monitoring helpers |
| [`harness-crossreview.schedule.snippet.yml`](harness-crossreview.schedule.snippet.yml) | Disabled example schedule for PR cross-review. | Operator copying into an installed runtime registry |
| [`harness-routing.yml`](harness-routing.yml) | Maps implementation/review task types to Claude or Codex. | `agentic-harness-run`, PR cross-review |
| [`health-monitor.yml`](health-monitor.yml) | Queue, runtime, disk, and process health thresholds. | `agentic-os-monitor` |
| [`hosts-routing.yml`](hosts-routing.yml) | Example cross-host roles, paths, harnesses, and concurrency. | `agentic-harness-run` |
| [`intake-routing.yml`](intake-routing.yml) | Natural-language project routing for unified intake. | `agentic-os-intake-row` |
| [`intake-sync.yml`](intake-sync.yml) | Notion-to-Linear intake synchronization mapping. | `agentic-os-intake-sync` |
| [`skills.yml`](skills.yml) | Canonical skill identity, description, and source path. | capability registry and harness skill registration |
| `reports.yml` (installed) | Governed report prompt/catalog entries in draft or archived lifecycle. | registry resource authoring and Command Center discovery |
| `report-definitions.yml` (installed) | Runnable, versioned report sources, sections, schedule, destinations, permissions, and health. | `agentic-os report` engine and Command Center typed query |

Registry schemas live in [`../../schemas/`](../../schemas/). Neutral example
values must remain safe to publish; installed overrides carry real host,
workspace, or project identity.

The first-class resource snapshot is derived installed state, not an authoring
surface. Canonical definitions remain in their scoped registries and resource
folders. Governed authoring refreshes the snapshot automatically; use the
explicit refresh command after manual filesystem changes.
