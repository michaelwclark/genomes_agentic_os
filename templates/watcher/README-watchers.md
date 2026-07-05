# Watchers

Watchers are lightweight polling loops that watch external sources and trigger OS actions.
Each watcher lives in its own subfolder here, runs independently, and writes structured
artifacts so every run is auditable.

## What a watcher is

A watcher:
- Polls one external source (a Notion database, a Slack channel, a local folder, etc.)
- Applies a filter to find new or changed items
- Takes a bounded action per item (queue a harness run, create an intake row, notify)
- Writes per-run artifacts under its own `runs/` directory
- Fires `agentic-os-notify` so you see it in macOS notifications

A watcher does NOT push code, post to external services, or take irreversible actions
without explicit configuration (`auto_mode: true` in the item itself).

## Folder anatomy

```
watchers/
  <name>/
    watcher.yml        # Config: poll interval, source, project map, concurrency limits
    runbook.md         # Plain-English: what it watches, when to expect it, failure playbook
    schedule.snippet.yml  # Copy of the runtime-registry entry (not registered here — read-only)
    scripts/
      watch.py         # The watcher script. Supports --once and --dry-run.
    runs/              # Gitignored artifacts. One folder per tick: <ts>-<id8>/
```

## How to add a new watcher

1. Copy `templates/watcher/` from the repo (`/Users/genome/projects/genomes_agentic_os/templates/watcher/`).
2. Fill in `watcher.yml` — source, filters, project_cwd_map, harness_run_cmd.
3. Write `scripts/watch.py` following the pattern in `notion_work_intake/scripts/watch.py`.
   If the watcher can execute `agentic-harness-run --harness auto`, it must pass
   a resolved `--task-type`, forward `harness_run_timeout_sec` as `--timeout-sec`,
   honor `harness_run_outer_grace_sec`, and preserve stderr/stdout tails in its
   result artifact when execution fails.
4. Write `runbook.md` (what it does, expected cadence, failure playbook).
5. Add a `schedule.snippet.yml` matching the runtime-registry entry format.
6. Test with `python3 scripts/watch.py --once --dry-run`.
7. Register in `harness/shared_factory/00-control-plane/runtime-registry.yml`
   by appending the schedule entry (copy from `schedule.snippet.yml`).
8. Add the source to `harness/registries/alerts.yml` so notifications route correctly.

## How scheduling works

Watchers are driven by the runtime supervisor, which reads `runtime-registry.yml`
and executes scheduled entries on their cadence. Each watcher's `schedule.snippet.yml`
contains the entry to paste into that file when you're ready to enable it.

To run a watcher manually for testing:
```
cd watchers/<name>
python3 scripts/watch.py --once
python3 scripts/watch.py --once --dry-run
```

After registering a watcher command in the runtime registry, run:
```
agentic-os runtime doctor --root /Users/genome/agentic_os
```

The doctor should report the watcher command as supported. Registered watcher
commands are limited to `python3 <root>/watchers/<id>/scripts/<script>.py --once`
with a sibling `watcher.yml`.

To run continuously in the foreground (useful before enabling the supervisor):
```
python3 scripts/watch.py
```

## Installed watchers

| Name | Source | Cadence | Status |
|---|---|---|---|
| `notion_work_intake` | Notion "OS Work Intake" DB | 10 min | enabled=false (ready to activate) |
| `notion_granola` | Notion search for Granola meeting notes | 60 min | draft (needs source discovery) |

## Gitignore

`runs/` directories contain large artifacts and are excluded from version control.
Add `watchers/*/runs/` to `.gitignore` if this directory is tracked.
