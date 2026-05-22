# 56 Universal Agent Brain Convention And Prompt Stitching

## Source Card

- ID: `368683b4-8dab-8137-96a4-f8b38619482a`
- Branch: `codex/build-runner-56`

## Scope

Codify how Agentic OS prompt and context files compose inside Codex and Claude
oriented directories without adding Mermaid diagrams or turning Notion into the
runtime database.

## Acceptance

- Define canonical roles for `AGENTS.md`, `CLAUDE.md`, `BRAIN.md`,
  `ROUTER.md`, `CONTEXT.md`, `MEMORY.md`, and workflow-local files.
- Explain which files are universal, harness-specific, and generated from
  templates.
- Provide migration guidance for existing duplicated docs.
- Add examples showing nested prompt stitching from OS root to workflow
  directory.
