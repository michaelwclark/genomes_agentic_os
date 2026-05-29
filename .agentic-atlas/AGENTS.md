# AGENTS.md — .agentic-atlas

**If you are an agent working in this repository, read
[`START-HERE.md`](START-HERE.md) before doing anything else.**

This folder (`.agentic-atlas/`) is the **canonical, validated inventory** of
Genome's Agentic OS. It exists so you do **not** re-analyze the codebase from
scratch. It contains:

- [`START-HERE.md`](START-HERE.md) — the index and resume guide (start here).
- [`architecture/system-architecture.md`](architecture/system-architecture.md) — the architecture + how to extend without making a mess.
- [`architecture/harness-modes.md`](architecture/harness-modes.md) — Claude vs Codex: identical core, differing install/config/invocation.
- [`architecture/command-reference.md`](architecture/command-reference.md) — every command and flag, with real examples.
- [`gap-register.md`](gap-register.md) — what's designed-but-not-running + missing services.
- [`backlog.md`](backlog.md) — prioritized features / fixes / upgrades.
- [`validation/`](validation/) — the pass/guard matrix and real command output.
- [`tools/`](tools/) — re-runnable validation + diagram-render scripts.

## Routing for common asks

| If the user asks… | Go to |
| --- | --- |
| "how does X work / where is X" | `architecture/system-architecture.md` then the module named there |
| "what does command Y do / what flags" | `architecture/command-reference.md` |
| "what's broken / missing / not running" | `gap-register.md` |
| "what should we build next" | `backlog.md` |
| "is it actually working" | run `tools/validate-cli.sh` + `pytest -q`, compare to baseline in `START-HERE.md` |

## Working rules (inherited from the architecture map)

- Names are **snake_case**. Effects are **dry-run by default** (`--apply` to commit).
- The **filesystem is the source of truth**; Notion/DB are projections.
- New commands follow the §9 extension recipe (parser + thin handler → `*_ops.py` →
  template → schema → registry entry → test). No `utils.py`, no globals, no
  in-process event bus, no non-deterministic routing.
- **Validate before and after.** Update this atlas (backlog status, gap register,
  baseline date) when you finish substantive work.
