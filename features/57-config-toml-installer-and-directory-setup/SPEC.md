# 57 config.toml Installer And Directory Setup

## Source Card

- ID: `368683b4-8dab-81e9-a9f3-ec46415e3796`
- Branch: `codex/build-runner-57`

## Scope

Create the CLI/install path that writes or updates `config.toml` files for new
and existing Agentic OS directories.

## Acceptance

- Installer supports dry-run, apply, backup, idempotent re-run, and
  user-preserving merge behavior.
- New OS, customer, domain, workflow, and automation directories receive the
  correct `config.toml` template and prompt-file convention.
- Existing configs are not overwritten without a clear diff and confirmation
  path.
- Tests cover creation, merge, conflict, missing-directory, and repeated-run
  behavior.
