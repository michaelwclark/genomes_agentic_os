# Holdout QA

Before implementation is accepted, validate with fixtures that include:

- a raw LOS Django idea with no project selected
- a LOS Django project idea that promotes to a Jira-targeted local mirror
- a `genomes_agentic_os` feature request that names `60-memory-driven-toolsmith-loop`
- a stale work item stuck in `building`
- a finished work item with no validation evidence
- a documented work item with no memory or docs update
- a synthetic Claude stop payload with transcript path
- a synthetic Codex stop payload with transcript path
- a transcript containing MCP calls, skills, shell commands, subagents, and tests
- token-shaped values that must be redacted before writing sidecars
- an older install that still has top-level `shared_factory/`

Expected result: routing identifies the right work item, lifecycle state drives
the required read/write list, logs are written with redaction, and validation
reports lifecycle drift without overwriting user state.
