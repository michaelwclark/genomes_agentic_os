# CLI And Install

The V1 CLI is a scaffold and validation tool. It creates the local filesystem shape that humans, agents, and future automations can use as a shared operating surface.

It does not run automations for you yet. It creates the durable places where automation definitions, workflow specs, context packs, and run logs live.

## Install

Use a virtual environment so the package and its development dependencies stay isolated from the system Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For local test work:

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

Confirm the command is installed:

```bash
agentic-os --help
```

## Command Flow

The CLI flow should mirror the operating model:

| Step | Command | Why It Exists |
| --- | --- | --- |
| Create OS root | `agentic-os init --target ~/agentic_os` | Establishes the durable folders and copies source templates. |
| Create domain | `agentic-os domain create internal_product --root ~/agentic_os` | Creates the operating boundary and context placeholders. |
| Create workflow | `agentic-os workflow create internal_product engineering feature_dev --root ~/agentic_os` | Adds a repeatable process spec for judgment-heavy work. |
| Create automation | `agentic-os automation create internal_product support production_thread_intake --root ~/agentic_os` | Adds a guarded trigger-driven process spec. |
| Create run log | `agentic-os run-log create internal_product feature_dev --root ~/agentic_os` | Records one execution attempt for audit and handoff. |
| Validate | `agentic-os validate --root ~/agentic_os` | Checks the required tree and parseable structured files. |

## Smoke Test

Use a temporary directory first:

```bash
tmpdir=$(mktemp -d)
agentic-os init --target "$tmpdir/os"
agentic-os domain create internal_product --root "$tmpdir/os"
agentic-os workflow create internal_product engineering feature_dev --root "$tmpdir/os"
agentic-os automation create internal_product support production_thread_intake --root "$tmpdir/os"
agentic-os run-log create internal_product feature_dev --root "$tmpdir/os"
agentic-os validate --root "$tmpdir/os"
find "$tmpdir/os" -maxdepth 4 -type f | sort
```

Expected result:

- `validate` exits successfully.
- `domains/internal_product/domain.yml` exists.
- `domains/internal_product/context/` has business, systems, stakeholders, and access policy placeholders.
- `domains/internal_product/workflows/engineering/feature_dev.md` exists.
- `domains/internal_product/automations/support/production_thread_intake.md` exists.
- `runs/` contains a timestamped run log.
- `templates/` contains copied source templates.

## What The CLI Copies

`init` copies the repository `templates/` tree into the installed OS. This matters because the installed OS should remain usable even when an agent is operating from the runtime root instead of this source repository.

Source templates stay in this repo. Runtime copies live under the installed OS and can be referenced by agents during execution.

## Rerun Safety

V1 commands are intentionally conservative:

- Existing files are not overwritten.
- Existing folders are reused.
- Re-running a scaffold command should not erase hand-authored context.
- New run logs use timestamped names so each execution gets its own record.

If a template needs to update existing installed files in a future version, that should be an explicit migration command with a reviewable diff.

## Validation Scope

V1 validation checks:

- Required installed folders exist.
- JSON files under the OS root are parseable.
- YAML files under the OS root are parseable.

V1 validation does not yet:

- Enforce every JSON Schema.
- Validate Markdown table contents.
- Check external links.
- Verify Notion page IDs or database IDs.
- Confirm Claude or Codex skill installation.

## Real Install Checklist

Before using a real `~/agentic_os` root:

1. Run the smoke test in a temporary directory.
2. Run `agentic-os init --target ~/agentic_os`.
3. Create one domain.
4. Fill the domain context files before running real work.
5. Add one workflow before adding automations.
6. Keep automation permissions at `observe` or `prepare` until approval and rollback rules are explicit.
7. Create run logs for non-trivial agent sessions.
8. Run `agentic-os validate --root ~/agentic_os` before handing the OS to another agent.
