# Build Runner Holdout QA Results Log

## 00 Current State And Gap Map

- `uv run pytest -q`: `7 passed in 0.48s`.
- `uv run agentic-os validate --root ~/agentic_os`: `valid: /Users/genome/agentic_os`.
- Notion update/comment writes returned HTTP 200.

## 01 Project Create And Active Work

- `uv run --extra dev pytest -q`: `10 passed in 0.62s`.
- Temp-root smoke with `agentic-os init`, `agentic-os project create los losmon_replacement`, and `agentic-os validate`: `valid`.

## 02 Routing And Context Builder

- `uv run --extra dev pytest -q`: `14 passed in 0.83s`.
- Temp-root route, linked-repo `here context build`, and validation smoke passed.

## 03 Workflow Readiness And Run Closeout

- `uv run --extra dev pytest -q`: `17 passed in 1.13s` on merged `main`.
- Temp-root workflow check, run-log close, and validation smoke passed.
- Notion completion write/comment returned HTTP 200.

## 04 Automation Maturity And Reconfiguration

- `uv run --extra dev pytest -q`: `20 passed in 1.28s` on merged `main`.
- Temp-root automation check, set-maturity prepare, attach, and validation smoke passed.
- Notion completion write/comment returned HTTP 200.
