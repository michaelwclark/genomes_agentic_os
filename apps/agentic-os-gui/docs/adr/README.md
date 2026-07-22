# Architecture Decision Records — Agentic OS Command Center

This directory records the decisions that shape `apps/agentic-os-gui`, in the
order they were made. It exists so a future engineer-agent can answer "why is
it built this way" without re-deriving the reasoning from the diff, and so a
decision that stops making sense has a named place to be revisited instead of
being silently worked around.

## Reading these ADRs

**Status describes the decision, not the implementation.** An ADR can be
`Accepted` — the decision is final and future code should follow it — while
the code that implements it is still landing. Where that's true, the ADR body
says so explicitly, inline, with a `(planned — Phase N)` marker tied to a
phase in [`../ROADMAP.md`](../ROADMAP.md). Do not assume a file path cited in
an ADR exists yet; check the marker. Where no marker appears, the citation was
verified against the tree at the time the ADR was written — trees drift, so
verify again if it matters to what you're about to do.

## Format contract

Every ADR in this directory uses exactly these five `##` sections, in this
order:

| Section | Content |
|---|---|
| **Status** | One of `Proposed`, `Accepted`, `Accepted, phased`, `Superseded by ADR-NNNN`, `Deprecated`. Phased/retroactive qualifiers go here, e.g. `Accepted (retroactive record of existing design)`. |
| **Context** | The situation that forced a decision: what exists today (cited, with file paths), what constraint or problem is in play, what options were on the table. |
| **Decision** | What was decided, stated as a rule a future contributor can follow without re-reading the Context. Cites the concrete implementation (function/class/file) where one exists; marks `(planned — Phase N)` where it doesn't yet. |
| **Consequences** | What this decision costs, what it forecloses, what it enables. Honest about the downside, not just the upside. |
| **Revisit-when** | A concrete, checkable trigger — a number, an event, a condition someone can observe without asking the ADR's author what they meant. Never "if requirements change." |

New ADRs: copy this section shape, allocate the next `NNNN`, add a row to the
index below in the same edit.

## Index

| # | Title | Status | Summary |
|---|---|---|---|
| [0001](0001-cli-bridge-over-direct-db-reads.md) | CLI bridge over direct DB reads | Accepted (retroactive record of existing design) | The GUI reads OS state only by spawning the `agentic-os` CLI (`gui snapshot\|transcript --json`); it never opens `state.db` or JSONL directly. |
| [0002](0002-admin-dashboard-in-app-not-adminjs.md) | Admin dashboard in-app, not AdminJS | Accepted | Admin/inspection surfaces are pages inside the command center (page registry + feature modules), not AdminJS and not a separate web app for v1. Mutations go through governed CLI commands only. |
| [0003](0003-event-and-streaming-backbone.md) | Event and streaming backbone | Accepted, phased | A typed main-process EventBus (losmon precedent) bridged to the renderer over one multiplexed `aos:feed-event` IPC channel, consumed via a `useFeed(topic)` hook. Decision and contracts recorded now; implementation is Phase 2. |
| [0004](0004-ui-state-tiers-and-caching.md) | UI state tiers and caching | Accepted | Five state tiers with a hard rule for where new state goes: ephemeral React state, `aos.layout.v1` (chrome only), `operator-state.json` (operator semantics), main-process in-memory caches, and the OS state plane itself (never cached to disk, never written directly). |

## Related docs

- [`../ROADMAP.md`](../ROADMAP.md) — phases these ADRs' `(planned — Phase N)` markers point into, with exit criteria.
- `../ARCHITECTURE.md`, `../FEATURE-PLAYBOOK.md`, `../DATA-AND-EVENTS.md`, `../DESIGN-SYSTEM.md` — sibling docs covering the areas these ADRs don't: overall system shape, the feature-module recipe, event/data contracts in full, and visual design tokens respectively. Not authored by this pass — referenced here by name and purpose only.
