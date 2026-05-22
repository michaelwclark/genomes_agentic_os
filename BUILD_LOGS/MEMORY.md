# Build Runner Memory Log

## 00 Current State And Gap Map

- Notion connector was unauthorized; direct API fallback worked.
- Use `uv run` for verification because `python` is not on PATH in the context shell.
- The root worktree was dirty before this run; next build-runner work should start from a clean commit or explicit dirty-baseline approval.

## 01 Project Create And Active Work

- Worktree-local `uv run pytest` needed `--extra dev` when the worktree venv was fresh.
- Project create should stay additive: do not rewrite project files; append missing index/source rows only.

## 02 Routing And Context Builder

- Deterministic routing can use project `sources.repo` to map external cwd values back into the installed OS project tree.
- Route commands are read-only by default; context packets are printed YAML.

## 18 Documentation And Help Guide For 00 Current State And Gap Map

Feature guide docs currently live under `docs/13-feature-guides/`. Feature 00 documentation should explain source/runtime boundaries and the plan mirror path rather than introducing new runtime commands.

## 19 Holdout Command Validation For 00 Current State And Gap Map

Feature 00 holdout checks should avoid live Notion writes and prefer local source, runner-state, and disposable-runtime evidence.

## 20 Documentation And Help Guide For 01 Project Create And Active Work

Project-create guidance should emphasize additive writes, active-work discovery, source-map references, and `lenders` to `los` alias behavior.

## 21 Holdout Command Validation For 01 Project Create And Active Work

Feature 01 holdout validation should check active-work/project indexes, source-map rows, idempotency, and `lenders` to `los` aliasing.
