# 05 · Routing & Context

> **Purpose:** turn "where does this work belong, and what should I load?" into a
> deterministic, auditable answer — with **no model guesswork**. This is the step
> that hands an agent the *right files at the right moment* (the core MWP idea).
>
> **You'll use:** `agentic-os route`, `agentic-os here route|context`, `agentic-os context build`.
> **Prereqs:** an installed OS root ([01 · Install & Quickstart](01-install-and-quickstart.md)) with at least one domain/project.

---

## The idea

Routing answers two questions deterministically, in `routing.py` — **never with an
LLM call**:

1. **Where does this belong?** A domain, a lane, a project, or a workflow.
2. **What is the minimal context to load?** An ordered list of files, plus the
   approval risks and known gaps.

The output is a **`ContextPacket`** — the contract handed to whichever harness is
driving. If routing can't match with confidence, it **refuses** (exit code 2)
rather than guess.

![Routing flow: a request or cwd is matched deterministically against known domains/projects/lanes; low-confidence refuses with exit 2; a confident match scans for approval-risk keywords and assembles a ContextPacket of sources, risks, gaps, and a handoff prompt](diagrams/routing-flow.png)

---

## Commands & flags

### `agentic-os route <request>`
Route a free-text request from anywhere.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `request` | ✅ (positional) | The work request, in quotes. |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

### `agentic-os here route <request>` / `agentic-os here context build`
Route/build **from the current working directory** — infers the domain/project
from where you are (looks up the tree for the `.agentic_root` marker).

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `request` | ✅ for `here route` | The request string. |
| `--root` | — | Override the detected root. |

### `agentic-os context build --domain <d>`
Build a context packet for a specific target without a request string.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--domain` | ✅ | Domain to scope to. |
| `--project` | — | Narrow to a project. |
| `--workflow` | — | Narrow to a workflow. |
| `--lane` | — | Narrow to a lane. |
| `--root` | — | Installed OS root (default `~/agentic_os`). |

---

## Worked example (real output)

```bash
agentic-os route "ship the launch blog post" --root ~/agentic_os
```

```text
domain: acme
lane: ''
object_type: project
target_path: .../acme/02-projects/launch
sources_to_load:
- .../ROUTER.md
- .../shared_factory/05-knowledge/references/naming-conventions.md
- .../shared_factory/05-knowledge/references/tool-index.md
- .../acme/ROUTER.md
- .../acme/CONTEXT.md
- .../acme/00-control-plane/active-work.md
- .../acme/02-projects/launch/project.yml
- .../acme/02-projects/launch/status.md
- .../acme/02-projects/launch/source-map.md
approval_risks: []
known_gaps: []
handoff_prompt: Load the listed sources, work in .../acme/02-projects/launch,
  follow approval rules, and record validation before closeout.
```

`context build --domain acme --project launch` produces the same packet without a
request string — useful when you already know the target.

---

## The `ContextPacket` (what every route returns)

| Field | Meaning |
| --- | --- |
| `domain`, `lane`, `object_type` | Where the work lands. |
| `target_path` | The working directory for the run. |
| `sources_to_load` | The **ordered, minimal** set of files to read first — root routers → shared references → domain context → the specific object. |
| `approval_risks` | Risks detected in the request (see below). |
| `known_gaps` | Missing context the agent should be aware of. |
| `handoff_prompt` | The ready-to-use instruction handed to the harness. |

This is MWP in one object: instead of dumping a whole repo into a prompt, routing
computes the *small ordered set* that matters and the risks attached to it.

## Approval-risk detection

Routing scans the request for `RISK_KEYWORDS` and surfaces them in
`approval_risks`, so risky work hits an approval gate before execution:

| Keyword(s) | Flagged risk |
| --- | --- |
| `external`, `send` | external write |
| `customer` | customer-visible output |
| `production`, `deploy`, `merge` | production change |
| `delete`, `destroy` | destructive action |
| `secret` | secret handling |
| `billing`, `legal` | billing or legal record |

---

## Running this from Claude vs Codex

> Same routing logic, same `ContextPacket`, same run log — only the trigger differs.

- **Claude:** run the `/os-route` command, or invoke the **`os-navigator`** skill
  (it wraps route + context-pack building). Context loading mirrors Codex.
- **Codex:** run `agentic-os route "<request>" --root ~/agentic_os` (or
  `here route` from inside a domain). The `domain_or_lane` profile in that folder's
  `config.toml` governs the model, tool allow-list, and validation hooks.

Full mechanics and setup: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **Low-confidence refusal (exit 2).** If nothing matches confidently, you'll see
  `error: routing confidence is low: no domain or project matched`. This is
  intentional — name the domain/project explicitly, or `cd` into it and use
  `here route`. (See [18 · Troubleshooting](18-troubleshooting-and-faq.md).)
- **Names are snake_case.** `launch_blog`, not `launch-blog`.
- **Routing reads, never writes.** `route`/`context build` are safe to run anytime;
  they only compute and print.

## Related

- [03 · Operating Model](03-operating-model.md) — where routing sits in the loop.
- [04 · Information Architecture](04-information-architecture.md) — the domains/lanes routing matches against.
- [06 · Workflows](06-workflows.md) — what you do once routed to a workflow.
- Atlas: [`architecture/system-architecture.md` §7](../.agentic-atlas/architecture/system-architecture.md) · [`command-reference.md`](../.agentic-atlas/architecture/command-reference.md)
