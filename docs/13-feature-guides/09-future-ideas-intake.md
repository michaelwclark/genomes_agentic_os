# 09 Future Ideas Intake

## Table Of Contents

- [Purpose](#purpose)
- [Command](#command)
- [Routing Rules](#routing-rules)
- [Additive Behavior](#additive-behavior)
- [Validation](#validation)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 09 gives future ideas a durable intake path so they do not remain only
in chat. The command routes ideas into the installed OS filesystem according to
scope: reusable OS ideas, domain ideas, and customer or project ideas.

## Command

Capture an OS-level idea:

```bash
agentic-os plan capture --root ~/agentic_os \
  --title "Capture telemetry into run logs" \
  --summary "Make telemetry evidence available in closeout records."
```

Capture a domain idea:

```bash
agentic-os plan capture --root ~/agentic_os \
  --kind domain \
  --domain acme \
  --title "Improve deploy triage" \
  --summary "Collect deploy risk patterns before release branches."
```

Capture a project or customer idea:

```bash
agentic-os plan capture --root ~/agentic_os \
  --kind customer \
  --domain acme \
  --project launch \
  --title "Customer validation script" \
  --summary "Create a repeatable read-only validation script."
```

## Routing Rules

- `--kind os` writes a markdown file under
  `harness/shared_factory/05-knowledge/plans/future-ideas/` and appends it to
  the shared plans index.
- `--kind domain` appends to `<domain>/01-inbox/raw-ideas.md`.
- `--kind customer` with `--project` creates a captured project work item under
  `<domain>/02-projects/<project>/work-items/01-intake/NNN_slug.md` and appends
  status/control-plane indexes.
- Expanded intake may use a folder packet at
  `<domain>/02-projects/<project>/work-items/01-intake/NNN_slug/` when a duel or
  spec pass creates multiple files. Subtasks keep the parent index, for example
  `NNN_01_update_database.md`.

Domain and customer captures require `--domain`. Project captures require an
existing project status file.

## Additive Behavior

Plan capture is additive. It appends or creates durable records and should not
overwrite existing runtime notes.

Use it during chats, triage, and reviews whenever an idea is real enough to
preserve but not ready for the active build queue.

## Validation

After capturing ideas, run:

```bash
agentic-os validate --root ~/agentic_os
```

The capture path should preserve installed root validation.

## Source Artifacts

- Installed spec: `SPECS/09-future-ideas-intake/SPEC.md`
- Installed worklog spec: `worklogs/source-features/09-future-ideas-intake/SPEC.md`
- Installed worklog QA: `worklogs/source-features/09-future-ideas-intake/HOLDOUT_QA.md`
- Implementation: `src/genomes_agentic_os/plans.py`
- CLI wiring: `src/genomes_agentic_os/cli.py`
- Test coverage: `tests/test_cli_scaffold.py`
