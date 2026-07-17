# `agentic-os develop`

Canonical entry point for one or many Agentic OS programming tasks.

```bash
# Plan only (default)
agentic-os develop start <domain> <project> <ticket> [<ticket> ...]

# Provision portfolio, one active work item, and one isolated worktree per task
agentic-os develop start <domain> <project> <ticket> [<ticket> ...] --apply

# Compact portfolio/task readback
agentic-os develop status <run-dir>
```

Project behavior comes from `config/development.yml`. The program contract and
five complete workflow specifications live in
`harness/shared_factory/00-programs/development_delivery/` and
`harness/shared_factory/04-workflows/development_delivery/`.

Transitions, failures, and recovery are receipt-backed:

```bash
agentic-os develop transition <state.json> --to <state> --receipt <ref> --idempotency-key <key>
agentic-os develop fail <state.json> --kind <classification> --detail <text> --receipt <ref> --idempotency-key <key>
agentic-os develop recover <state.json> --receipt <ref> --idempotency-key <key>
agentic-os develop heartbeat <state.json> --owner <worker> --idempotency-key <key>
```
