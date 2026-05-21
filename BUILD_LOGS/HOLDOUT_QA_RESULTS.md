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

## 05 Customer Os Factory

- `uv run --extra dev pytest -q`: `23 passed in 1.27s` on merged `main`.
- Temp customer init, update, validate, and private-name scan passed.
- Notion completion write/comment returned HTTP 200.

## 06 Notion Control Plane Sync

- `uv run --extra dev pytest -q`: `25 passed in 1.36s` on merged `main`.
- Temp-root Notion plan/refusal/apply/idempotency smoke passed.
- Notion completion write/comment returned HTTP 200.

## 07 Doctor Validation And Migrations

- `uv run --extra dev pytest -q`: `27 passed in 1.64s` on merged `main`.
- Temp-root doctor missing/fix/stale-run and migration plan/apply smoke passed.
- Notion completion write/comment returned HTTP 200.

## 08 Losmon Replacement Validation

- `uv run --extra dev pytest -q`: `28 passed in 1.72s` on merged `main`.
- Temp-root LOSMon validation package and root validation smoke passed.
- Notion completion write/comment returned HTTP 200.

## 09 Future Ideas Intake

- `uv run --extra dev pytest -q`: `29 passed in 1.80s` on merged `main`.
- Temp-root OS/domain/project plan capture and validation smoke passed.
- Notion completion write/comment returned HTTP 200.

## 10 Notion Control Plane Bootstrap

- `uv run --extra dev pytest -q`: `30 passed in 1.85s` on merged `main`.
- Temp-root Notion bootstrap dry-run/refusal/apply smoke passed.
- Notion completion write/comment returned HTTP 200.

## 11 Room First Installer And Routing

- `uv run --extra dev pytest -q`: `32 passed in 1.92s` on merged `main`.
- Temp room-profile validate/init/validate smoke passed.
- Notion completion write/comment returned HTTP 200.

## 12 Factory Template Import Backlog

- `uv run --extra dev pytest -q`: `33 passed in 1.96s` on merged `main`.
- Temp-root docs update/template smoke passed.
- Notion completion write/comment returned HTTP 200.
