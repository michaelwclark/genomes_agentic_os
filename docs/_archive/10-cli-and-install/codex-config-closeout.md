# Codex Config Closeout And Holdout Validation

## Table Of Contents

- [What Shipped](#what-shipped)
- [How-To Flows](#how-to-flows)
- [Command Help Verified](#command-help-verified)
- [Holdout Matrix](#holdout-matrix)
- [Default Codex Summarizer Summary](#default-codex-summarizer-summary)
- [Validation Artifacts](#validation-artifacts)

## What Shipped

The Codex config feature set now includes:

- `docs/07-agent-surfaces/codex-config-toml-inventory.md`
- `docs/07-agent-surfaces/codex-config-profiles.md`
- `docs/07-agent-surfaces/universal-agent-brain.md`
- `docs/07-agent-surfaces/otel-and-mcp-configuration-contracts.md`
- `docs/10-cli-and-install/config-toml-installer.md`
- `agentic-os config install`
- `agentic-os config doctor`

## How-To Flows

Plan an install without writing:

```bash
agentic-os config install --root ~/agentic_os --layer agentic_os_root --dry-run
```

Apply after reviewing the diff:

```bash
agentic-os config install --root ~/agentic_os --layer agentic_os_root --apply --backup
```

Validate OTEL and MCP contracts:

```bash
agentic-os config doctor --root ~/agentic_os --layer agentic_os_root
```

Confirm non-conflicting additions while preserving local conflicting values:

```bash
agentic-os config install --root ~/agentic_os/los --layer domain_or_lane --apply --confirm-conflicts --backup
```

## Command Help Verified

Verified help surfaces:

- `agentic-os --help` lists the `config` command.
- `agentic-os config install --help` lists `--root`, `--layer`, `--dry-run`,
  `--apply`, `--backup`, and `--confirm-conflicts`.
- `agentic-os config doctor --help` lists `--root` and `--layer`.

## Holdout Matrix

Holdout root:

```text
/tmp/agentic-os-config-holdout-D7rPo2
```

Layer matrix:

| Layer | Dry-Run No Write | Apply | Re-Run | Doctor |
| --- | --- | --- | --- | --- |
| `global_harness` | passed | passed | passed | passed |
| `agentic_os_root` | passed | passed | passed | passed |
| `customer_os_root` | passed | passed | passed | passed |
| `domain_or_lane` | passed | passed | passed | passed |
| `workflow_or_task` | passed | passed | passed | passed |
| `automation` | passed | passed | passed | passed |

Additional paths:

| Path | Result |
| --- | --- |
| Conflict without `--confirm-conflicts` | blocked as expected |
| Conflict with `--confirm-conflicts --backup` | applied non-conflicting additions, backup present |
| Doctor after conflict-confirm merge | passed |
| Doctor on missing config | failed as expected with remediation |
| Full test suite | 46 passed in 3.14s |

## Default Codex Summarizer Summary

- All six Agentic OS config layers were exercised through dry-run, apply,
  idempotent re-run, and doctor validation.
- Dry-run mode produced no target directory writes for every layer.
- Apply mode generated `config.toml` and the layer prompt files, and repeated
  apply remained idempotent.
- Conflict handling blocked an unconfirmed local `model` override, then
  succeeded with `--confirm-conflicts --backup` while preserving the local
  value.
- `config doctor` passed after confirmed conflict merge and failed as expected
  for a missing config directory.
- The full test suite passed with 46 tests.

## Validation Artifacts

The feature-local validation log is:

```text
features/59-codex-config-documentation-and-holdout-validation/VALIDATION_LOG.md
```

The diagram used by the CLI guide is:

```text
docs/diagrams/codex-config-install-flow.svg
```
