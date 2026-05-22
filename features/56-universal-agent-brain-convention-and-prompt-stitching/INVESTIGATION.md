# Investigation

Feature 54 established that Codex discovers `AGENTS.md` while the Agentic OS
also carries Claude-compatible `CLAUDE.md` files and universal router/context
files. The repo already scaffolds `ROUTER.md`, `AGENTS.md`, `CLAUDE.md`,
`CONTEXT.md`, and memory policy material, but it did not yet define the
universal brain file or the exact prompt stitching order.

The convention therefore keeps harness-specific entry files thin and moves
durable cross-harness behavior into universal files.
