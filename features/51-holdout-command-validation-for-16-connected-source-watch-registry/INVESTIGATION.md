# Investigation

Feature 16 exposes file-backed connected source watching through
`agentic-os connected-system` and `agentic-os watch-source`.

The relevant implementation is `src/genomes_agentic_os/source_watch.py`.
Runtime templates include `connected-system.yml`, `source-provider.yml`,
`watch-source.yml`, `watch-cursor.yml`, `source-event.yml`, and
`trigger-rule.yml`. The command prompt is `harness/commands/os-watch-source.md`,
and the operator skill is `harness/skills/source-watcher/SKILL.md`.

The holdout reused the public command surface rather than calling internal
Python helpers.
