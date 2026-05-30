# 🗺️ .agentic-atlas — Start Here

> **You are in the canonical inventory of Genome's Agentic OS.** This folder exists
> so that **no agent has to re-analyze the repo from scratch.** It is the durable,
> validated map of what the system is, what works, what's missing, and what to
> build next. Read this page first; follow the links; trust them over re-derivation
> (but re-validate if a fact looks stale — see the timestamp below).

**Last full validation: 2026-05-30** · CLI: **51 OK + 2 intentional guardrail exits** ·
Tests: **82/82 pass** · Diagram pipeline: **verified (Mermaid→PNG)**.

---

## What this system is (one paragraph)

`agentic-os` is a Python CLI that scaffolds and operates a **domain-first
filesystem "operating system" for AI-assisted work** at `~/agentic_os`. It is a
concrete implementation of the **Model Workspace Protocol** (arXiv:2603.16021):
numbered folders are stages, markdown files (`ROUTER/AGENTS/CONTEXT/RULES/TOOLS`)
carry context, local scripts do mechanical work, and one agent reads the right
files at the right moment. It runs from **either Claude or Codex**.

---

## The map (read in this order)

| # | File | What you'll learn |
| --- | --- | --- |
| 1 | [`architecture/system-architecture.md`](architecture/system-architecture.md) | **The architecture.** Five-layer model, the 20-module Python map, DI model, the file-backed event/reaction model, deterministic routing, enforced conventions, and **how to extend without making a mess**. |
| 2 | [`architecture/harness-modes.md`](architecture/harness-modes.md) | **Claude vs Codex.** What's identical (the whole operating loop) vs what differs (install/config/invocation only), plus the page→invocation map for writing per-page mode sections. |
| 3 | [`architecture/command-reference.md`](architecture/command-reference.md) | **Every command**, every flag, what it reads/writes, a real example, and its validated status. |
| 4 | [`gap-register.md`](gap-register.md) | **The honest delta** — designed-but-not-running (no always-on scheduler, plan-only Notion, unenforced schemas, no metrics), missing services, health posture. |
| 5 | [`backlog.md`](backlog.md) | **Prioritized features / fixes / upgrades** (P0–P2) with stable IDs, linked to the gaps. |
| 6 | [`validation/RESULTS.md`](validation/RESULTS.md) | The pass/guard matrix from the last harness run. |
| 7 | [`validation/command-output-examples.md`](validation/command-output-examples.md) | **Real stdout/stderr** to quote in docs — do not fabricate output. |

---

## Tools (re-runnable, durable)

| Tool | Run it | Does |
| --- | --- | --- |
| `tools/validate-cli.sh` | `bash .agentic-atlas/tools/validate-cli.sh` | Exercises the whole CLI against a **throwaway `/tmp` root** (never `~/agentic_os`), regenerates `validation/RESULTS.md` + `command-output-examples.md`. |
| `tools/render-diagrams.sh` | `bash .agentic-atlas/tools/render-diagrams.sh` | Renders every `*.mmd` under `docs/` and `.agentic-atlas/diagrams/` to PNG via local Chrome (no install). |
| `tools/puppeteer.json` | (config) | Points mermaid-cli at the installed Chrome. |

---

## If you are resuming this work

1. Read this page + the architecture map (1) — that's the whole system in ~10 min.
2. Re-validate the baseline: `bash .agentic-atlas/tools/validate-cli.sh` and
   `.venv/bin/python -m pytest -q`. If the numbers above changed, update them here.
3. Pick a `todo` item from [`backlog.md`](backlog.md) (work P0 → P2).
4. Follow the §9 extension recipe in the architecture map. Keep names snake_case,
   effects dry-run-by-default, files authoritative.
5. After substantive work, update the backlog status and the gap register.

## Hard facts (so you don't relearn them the hard way)

- **Names are snake_case** (lowercase, digits, `_`). Hyphens are rejected.
- **Exit codes:** `0` ok · `1` health "not ok" · `2` usage error *or* a deliberate
  refusal (e.g. low-confidence route). Non-zero is often a guardrail, not a crash.
- **`--root` defaults to `~/agentic_os`** — always pass it explicitly in scripts/tests.
- **Runtime/Notion/backup effects are dry-run by default** — need `--apply`.
- The **filesystem is the source of truth**; Notion and any future DB are projections.

---

## Human-facing documentation

The polished, diagram-rich handbook (19 pages, `00–18`, each with a compact
Claude-vs-Codex callout and embedded PNG diagrams) lives in
[`../docs/`](../docs/README.md) — start at its `README.md`. This atlas is the
**agent-facing** spine that the handbook was built from and validated against;
the deep Claude/Codex mechanics are on [`../docs/13-agent-surfaces.md`](../docs/13-agent-surfaces.md).
