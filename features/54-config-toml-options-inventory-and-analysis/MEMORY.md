# Memory

Codex config precedence is CLI/config overrides, profile, trusted project
`.codex/config.toml` layers from root to current directory, user config, system
config, then defaults.

Codex natively stitches `AGENTS.md`; Agentic OS files such as `BRAIN.md`,
`ROUTER.md`, and `CONTEXT.md` need fallback filename config, explicit
references, or generated `AGENTS.md` summaries.
