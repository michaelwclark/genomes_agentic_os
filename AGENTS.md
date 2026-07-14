# Agent Instructions

This repo defines Genome's Agentic OS: the reusable source package for scaffolding installed operating systems for agentic workflows.

## 🗺️ Start Here

**Before analyzing this repo, read the handbook index at [`docs/README.md`](docs/README.md)**
and the maintained architecture map so you don't re-derive the system from scratch:

- [`docs/architecture/system-architecture.md`](docs/architecture/system-architecture.md) — architecture + how to extend without making a mess.
- [`docs/architecture/command-reference.md`](docs/architecture/command-reference.md) — every command and flag, with real examples.
- [`docs/architecture/harness-modes.md`](docs/architecture/harness-modes.md) — how Claude/Codex surfaces execute the same specs.
- [`docs/architecture/tools/`](docs/architecture/tools/) — re-runnable validation + diagram-render scripts.

## Working Principles

- Treat this repo as product source, not the live installed OS.
- Keep docs actionable and implementation-oriented.
- Prefer templates and schemas over prose-only guidance.
- Do not add Mermaid diagrams. Use hand-authored SVG or PNG diagrams when diagrams are needed.
- Keep Claude and Codex surfaces aligned. They may install differently, but they must execute the same workflow specs.
- Do not assume Notion is the runtime database. Notion is the control plane.

## Expected Separation

| Path | Role |
| --- | --- |
| This repository | Source package for standards, docs, templates, schemas, and installers. |
| `~/agentic_os` | Installed operating system for live work. |
| `~/projects/*` | Product/client/code repositories operated by the OS. |

Project lifecycle state for this source package belongs in the installed OS
project at `<os-root>/<work-domain>/02-projects/genomes_agentic_os/`.
Do not recreate source-root `SPECS/`, `PLANS/`, `features/`, `BUILD_LOGS/`, or
`spec/` for Agentic OS planning or work history; use `work-items/`, `worklogs/`,
`logs/`, and `artifacts/` under the installed project instead.

## System Shell And Host Tools

- Treat host-level shell setup as part of the OS product surface.
- Before non-trivial shell, terminal, package-manager, runtime, or cleanup work, read the host tool registry when it exists.
- Source templates live in `templates/system/`; installed host registries live at `~/agentic_os/harness/shared_factory/05-knowledge/host-tool-registry.<host>.yml`.
- Keep interactive-only tools, such as iTerm2 utilities and fuzzy pickers, separate from automation-safe commands.

## Edit Style

- Add concrete files rather than vague planning notes.
- Keep templates copyable.
- Keep specs precise enough to become implementation tasks.
- Preserve existing user-authored content.
- For new source-package work, add or update an installed OS work item/spec
  first; keep this repo focused on product source files.
