# Genome's Agentic OS — Handbook

The complete guide to installing, operating, and extending **Genome's Agentic OS** —
a Python CLI (`agentic-os`) that scaffolds a domain-first filesystem "operating
system" for AI-assisted work. It is a concrete implementation of the **Model
Workspace Protocol** ([arXiv:2603.16021](https://arxiv.org/abs/2603.16021)):
numbered folders are stages, markdown files carry context, local scripts do the
mechanical work, and one agent reads the right files at the right moment.

> **The promise:** stop rebuilding operating context from scratch in every chat.

**Validated baseline (2026-06-09):** 53 CLI commands functional · 2 deliberate
guardrail exits · 0 crashes · 97/97 tests pass. Re-validate with
`bash .agentic-atlas/tools/validate-cli.sh` and `.venv/bin/python -m pytest -q`.

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
| **A builder** (extending the OS) | [02 · Architecture](02-architecture.md) → [`.agentic-atlas/`](../.agentic-atlas/START-HERE.md) (the architecture map + "how to extend without making a mess") |
| **An agent resuming work** | [`.agentic-atlas/START-HERE.md`](../.agentic-atlas/START-HERE.md) — the validated inventory, so you don't re-analyze the repo |

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
| [20 · Doc Config System](20-doc-config-system.md) | Configurable document routing across Agentic OS filesystem and Notion surfaces. |

Operator shortcut: use `/new-feature` for new feature or idea intake. It routes
through doc-config first, creates or repairs the project work item, and then
projects to Notion only after workspace verification.
Use `/add-bug` for lightweight bug or missed-enforcement capture, and
`/auto-add-feature` when a long OS-shaping request should become a local feature
packet before implementation continues.

---

## Supplementary & deep references

- **[Feature guides](13-feature-guides/)** — deeper, feature-by-feature implementation guides and gap maps.
- **[Tutorials](tutorials/)** — worked, scenario-based walkthroughs.
- **[The Atlas](../.agentic-atlas/START-HERE.md)** — the agent-facing, validated inventory: architecture map, command reference, harness-modes, gap register, backlog, and the re-runnable validation + diagram tools.
- **[`_archive/`](_archive/)** — the previous conceptual docs (superseded by the pages above; kept for history).

## About the diagrams

Diagrams are authored as Mermaid `.mmd` sources (gitignored, per repo policy) and
committed as rendered **PNG** under [`diagrams/`](diagrams/). Regenerate after any
edit with `bash .agentic-atlas/tools/render-diagrams.sh`.
