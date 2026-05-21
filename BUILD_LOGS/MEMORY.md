# Build Runner Memory Log

## 00 Current State And Gap Map

- Notion connector was unauthorized; direct API fallback worked.
- Use `uv run` for verification because `python` is not on PATH in the context shell.
- The root worktree was dirty before this run; next build-runner work should start from a clean commit or explicit dirty-baseline approval.
