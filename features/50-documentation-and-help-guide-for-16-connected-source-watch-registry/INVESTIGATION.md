# Investigation

Feature 16 adds a file-backed connected source registry for runtime source
watching.

The implementation lives in `src/genomes_agentic_os/source_watch.py` and is
exposed through `agentic-os connected-system` and `agentic-os watch-source`.
Runtime templates live under `templates/runtime/`, the command prompt lives at
`harness/commands/os-watch-source.md`, and the operating skill lives at
`harness/skills/source-watcher/SKILL.md`.

Tests in `tests/test_cli_scaffold.py` verify registry initialization, source
creation, doctor checks, dry-run polling, apply-mode source event writes,
cursor state, docs update repair, and negative doctor findings.
