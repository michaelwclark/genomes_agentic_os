# Build Runner Memory Log

## 00 Current State And Gap Map

- Notion connector was unauthorized; direct API fallback worked.
- Use `uv run` for verification because `python` is not on PATH in the context shell.
- The root worktree was dirty before this run; next build-runner work should start from a clean commit or explicit dirty-baseline approval.

## 01 Project Create And Active Work

- Worktree-local `uv run pytest` needed `--extra dev` when the worktree venv was fresh.
- Project create should stay additive: do not rewrite project files; append missing index/source rows only.
