# Agentic OS Command Center — Agent Entry Point

Local Electron desktop app ("Command Center") over the Agentic OS state plane.
Electron 43 + electron-vite 5 + React 19 + TypeScript strict + vitest.

## Read before you build

Read these in order before writing any code in this app. They exist so you
never re-derive the system, and they are maintained — if you change behavior
they describe, update them in the same change.

1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — process/layer model, IPC
   contract conventions, import rules, anti-patterns.
2. [docs/FEATURE-PLAYBOOK.md](docs/FEATURE-PLAYBOOK.md) — step-by-step recipes
   for adding pages, dashboards, watchers, panels, IPC capabilities.
3. [docs/DESIGN-SYSTEM.md](docs/DESIGN-SYSTEM.md) — design tokens
   ([src/renderer/theme/tokens.css](src/renderer/theme/tokens.css)), component
   conventions, data-viz standards. New styles use tokens, never raw hex.
4. [docs/DATA-AND-EVENTS.md](docs/DATA-AND-EVENTS.md) — where truth lives,
   read paths, streams, caching tiers, realtime rules.
5. [docs/adr/](docs/adr/README.md) — decision records. Do not relitigate an
   Accepted ADR in code; write a new ADR if circumstances changed.
6. [docs/ROADMAP.md](docs/ROADMAP.md) — phases and exit criteria.

## Commands

Run from this directory:

- `pnpm dev` — electron-vite dev app
- `pnpm typecheck` — tsc, must stay at 0 errors
- `pnpm test` — vitest, must stay green (69 tests as of Phase 1)
- `pnpm build` / `pnpm package:mac` — production bundle / mac app

## Hard rules

- OS state is read through the `agentic-os` CLI bridge only (ADR-0001) —
  never open `state.db` or OS files directly, never write OS state except via
  governed CLI commands.
- No new runtime dependencies without an ADR. The app deliberately ships
  react, react-dom, react-markdown, remark-gfm and nothing else.
- Renderer never touches `fs`, `process`, or Node APIs — everything crosses
  the preload bridge (`window.agenticOS`), typed in
  [src/shared/contracts.ts](src/shared/contracts.ts).
- Adding an IPC capability touches exactly four surfaces (IPC const, main
  handler, preload api, `AgenticOSApi`) — see FEATURE-PLAYBOOK Recipe E.
- New UI goes through the page registry
  ([src/renderer/pages/registry.tsx](src/renderer/pages/registry.tsx)) and the
  editor-group model — not ad-hoc overlays.
- Strict types at module boundaries; no `any`, no silent `as`.
- Tests are pure-function or static-markup style, co-located under
  [tests/](tests/). New logic ships with tests in that style.

## Wider system

This app lives inside the Agentic OS source repo — repo-root
[AGENTS.md](../../AGENTS.md) and the handbook
([docs/README.md](../../docs/README.md), page
[29 · AgenticOSGui](../../docs/29-agentic-os-gui.md)) govern everything above
the app. The system-wide tool inventory is
[docs/architecture/tool-catalog.md](../../docs/architecture/tool-catalog.md) —
check it before building any capability that might already exist.
