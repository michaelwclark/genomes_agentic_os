# Agent Instructions

This repo defines Genome's Agentic OS: the reusable source package for scaffolding installed operating systems for agentic workflows.

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

## System Shell And Host Tools

- Treat host-level shell setup as part of the OS product surface.
- Before non-trivial shell, terminal, package-manager, runtime, or cleanup work, read the host tool registry when it exists.
- Source templates live in `templates/system/`; installed host registries live at `~/agentic_os/shared_factory/05-knowledge/host-tool-registry.<host>.yml`.
- Keep interactive-only tools, such as iTerm2 utilities and fuzzy pickers, separate from automation-safe commands.

## Edit Style

- Add concrete files rather than vague planning notes.
- Keep templates copyable.
- Keep specs precise enough to become implementation tasks.
- Preserve existing user-authored content.
