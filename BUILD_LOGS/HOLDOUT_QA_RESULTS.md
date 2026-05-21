# Build Runner Holdout QA Results Log

## 00 Current State And Gap Map

- `uv run pytest -q`: `7 passed in 0.48s`.
- `uv run agentic-os validate --root ~/agentic_os`: `valid: /Users/genome/agentic_os`.
- Notion update/comment writes returned HTTP 200.

## 01 Project Create And Active Work

- `uv run --extra dev pytest -q`: `10 passed in 0.62s`.
- Temp-root smoke with `agentic-os init`, `agentic-os project create los losmon_replacement`, and `agentic-os validate`: `valid`.
