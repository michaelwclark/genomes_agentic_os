# Genome's Agentic OS — Handbook

The complete guide to installing, operating, and extending **Genome's Agentic OS** —
a Python CLI (`agentic-os`) that scaffolds a domain-first filesystem "operating
system" for AI-assisted work. It is a concrete implementation of the **Model
Workspace Protocol** ([arXiv:2603.16021](https://arxiv.org/abs/2603.16021)):
numbered folders are stages, markdown files carry context, local scripts do the
mechanical work, and one agent reads the right files at the right moment.

> **The promise:** stop rebuilding operating context from scratch in every chat.

**Test suite:** `.venv/bin/python -m pytest -q` is the source of truth for
current pass/fail status — this handbook does not track a frozen count because
it goes stale the moment a test is added. Re-validate the live CLI surface with
`bash docs/architecture/tools/validate-cli.sh`.

**Canonical doc split:** Use this `docs/` handbook when you are evaluating,
installing, or extending the source package and need architecture, command
reference, or validated behavior. If you are already operating inside an
installed OS at `~/agentic_os` and need runtime instructions for what to create,
where to put it, which format to use, or what evidence to leave behind, use the
[`operating-manual/`](../operating-manual/README.md); it is the operator/agent
manual copied into the installed OS.

---

## Runs from either harness

The OS is **harness-neutral**: the CLI, specs, routing, and run logs are identical
whether you drive it from **Claude** or **Codex**. Only install/config and the
invocation surface differ. Every page carries a compact **"Running this from Claude
vs Codex"** callout for its task; the full mechanics live on
[13 · Agent Surfaces](13-agent-surfaces.md).

## How to read this

| If you are… | Start here |
| --- | --- |
| **New** | [00 · Overview](00-overview.md) → [01 · Install & Quickstart](01-install-and-quickstart.md) → [03 · Operating Model](03-operating-model.md) |
| **An operator** (running daily work) | [03 · Operating Model](03-operating-model.md) → [05 · Routing](05-routing-and-context.md) → [06 · Workflows](06-workflows.md) → [08 · Runs](08-runs-and-run-logs.md) |
| **A builder** (extending the OS) | [02 · Architecture](02-architecture.md) → [`architecture/`](architecture/system-architecture.md) (the architecture map + "how to extend without making a mess") |
| **An agent resuming work** | [`architecture/system-architecture.md`](architecture/system-architecture.md) — the maintained architecture map, so you don't re-analyze the repo |

---

## The handbook

### Foundations
| Page | What it covers |
| --- | --- |
| [00 · Overview](00-overview.md) | What the OS is, the MWP paper, the five-layer model, the object hierarchy, V1 scope. |
| [01 · Install & Quickstart](01-install-and-quickstart.md) | Install the CLI, `init` an OS, smoke-test, create your first domain/project, first route. |
| [02 · Architecture](02-architecture.md) | Five-layer model, the Python package map, DI model, the file-backed event model, deterministic routing, conventions. |
| [03 · Operating Model](03-operating-model.md) | The intake → route → context → execute → validate → close → learn loop. |
| [04 · Information Architecture](04-information-architecture.md) | Domains, lanes, the numbered `00–08` folders, the context-file set, naming rules. |

### The operating loop
| Page | What it covers |
| --- | --- |
| [05 · Routing & Context](05-routing-and-context.md) | `route` / `here` / `context build`, the `ContextPacket`, deterministic risk detection. |
| [06 · Workflows](06-workflows.md) | Authoring workflow specs, the readiness files/sections, `workflow check`. |
| [07 · Automations](07-automations.md) | The maturity ladder, readiness, `automation check` / `set-maturity` / `attach`. |
| [08 · Runs & Run Logs](08-runs-and-run-logs.md) | `run-log create` / `close`, the audit-evidence gate, activity propagation. |

### Runtime, events & integration
| Page | What it covers |
| --- | --- |
| [09 · Runtime & Always-On](09-runtime-and-always-on.md) | `runtime` / `heartbeat` / `schedule` / `integration` — and the honest "no scheduler yet" gap. |
| [33 · Filesystem Resource Lifecycle](33-filesystem-resource-lifecycle.md) | Governed automation, workflow, program, and instance-program lifecycle plus queue-only run-now and derived schedules. |
| [10 · Events & Chains](10-events-and-chains.md) | The file-backed event ledger + declarative chain rules (the reaction model). |
| [11 · Connected Sources](11-connected-sources.md) | `connected-system` / `watch-source` registries and polling (contracts, not live yet). |
| [12 · Control Plane (Notion)](12-control-plane-notion.md) | `notion` sync/bootstrap as the human cockpit over the filesystem (plan-only in V1). |

### Surfaces, config & operations
| Page | What it covers |
| --- | --- |
| [13 · Agent Surfaces](13-agent-surfaces.md) | **The deep Claude-vs-Codex page** — shared core, the `@AGENTS.md` adapter, skills/commands, `config.toml` layers + profiles. |
| [14 · Config, Update & Backup](14-config-update-backup.md) | `.agentic_root`, `config`, `update` / `backup` / `license` / `migrate` — keeping an install current and recoverable. |
| [15 · Customer OS Factory](15-customer-os-factory.md) | `customer init/validate` + profiles/rooms — spinning up an isolated client OS. |
| [16 · Health, Doctor & Validation](16-health-doctor-validation.md) | `doctor`, the subsystem doctors, `validate`, the capability registry, the monitoring gap. |
| [20 · OS Cleanup Lifecycle](20-os-cleanup-lifecycle.md) | Cleanup workflow for terminal Jira or merged-PR worktrees, closed registry buckets, and active-work refresh. |
| [21 · OS Programs](21-os-programs.md) | OSProgram and InstanceOSProgram conventions for named capability CRUD across skills, commands, workflows, automations, docs, and state. |
| [24 · Auto-Dev Readiness](24-auto-dev-readiness.md) | The resolver-first gate for `$auto-dev`: lifecycle states, tracker preflight, backup/restore receipts, and closeout evidence. |
| [25 · Source Of Truth Rules](25-source-of-truth.md) | Where filesystem, Notion, Linear, Jira, and GitHub each own state, plus conflict and external-output rules. |
| [26 · Adaptive Routing Operator Guide](26-adaptive-routing.md) | Offline adaptive routing policy, lifecycle gates, redacted receipts, evaluation, rollback, and integration limits. |
| [27 · Engineering Cockpit](27-engineering-cockpit.md) | Local-first progressive view of conversations, work, reviews, reports, dynamic sources, hosts, automations, and hygiene. |

### Reference
| Page | What it covers |
| --- | --- |
| [17 · CLI Reference](17-cli-reference.md) | The navigable command map (links into the exhaustive atlas reference). |
| [18 · Troubleshooting & FAQ](18-troubleshooting-and-faq.md) | Common errors + fixes, the exit-code reference, and the honest known-limitations list. |
| [19 · Factory Patterns](19-factory-patterns.md) | Inventory of factory-derived assets and whether each was copied, adapted, referenced, or rejected when building the OS. |
| [22 · CLI Help Standard](22-cli-help-standard.md) | The help-text and argparse conventions every `agentic-os` command and harness script must follow. |
| [23 · Configuration Surfaces](23-configuration-surfaces.md) | Every configuration system the OS reads at runtime, how they interact, and which CLI commands manage them. |
| [28 · Doc Config System](28-doc-config-system.md) | Configurable document routing across Agentic OS filesystem and Notion surfaces. |
| [29 · Spec Engine](29-spec-engine.md) | Canonical idea-to-built lifecycle, layered policy, and filesystem/Linear/Jira adapters. |
| [30 · Compact Context Contracts](30-context-contracts.md) | Versioned inheritance manifests, explain/check commands, duplicate detection, and reversible dry-run migration plans. |
| [31 · First-Class Report Engine](31-report-engine.md) | Versioned report definitions, runs, artifacts, rich sections, governed lifecycle/run actions, and guarded projections. |
| [32 · Governed Registry Authoring](32-registry-resource-authoring.md) | Safe create/update/archive/restore/rollback for rules, reports, skills, and commands, plus analytics presentation metadata. |
| [34 · Activity Analytics Ingestion](34-activity-analytics-ingestion.md) | Privacy-safe provider event envelopes, opt-in scopes, metric bindings, cursors, and health. |

Operator shortcut: use `/add-spec` for ideas, features, bugs, configuration
changes, tickets, or backlog items. `/add-bug`, `/new-feature`, `/add-feature`,
`/new-idea`, `/groom-spec`, `/auto-add-spec`, and `/auto-add-feature` remain
compatibility adapters to the same Spec Engine.

---

## Supplementary & deep references

- **[Feature guides](13-feature-guides/)** — deeper, feature-by-feature implementation guides and gap maps.
- **[Tutorials](tutorials/)** — worked, scenario-based walkthroughs.
- **[Examples](examples/)** — small example domain OS trees used for exploration
  and documentation, not runtime templates.
- **[Architecture](architecture/system-architecture.md)** — the agent-facing architecture map, command reference, harness-modes, and the re-runnable validation + diagram tools under `architecture/tools/`.
- **[Design notes](design-notes/)** — in-progress design records for surfaces still taking shape (config.toml, lifecycle, port assessments).

## About the diagrams

Diagrams are authored as Mermaid `.mmd` sources (gitignored, per repo policy) and
committed as rendered **PNG** under [`diagrams/`](diagrams/). Regenerate after any
edit with `bash docs/architecture/tools/render-diagrams.sh`.
