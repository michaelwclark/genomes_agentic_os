# Holdout QA

## Checks

- Fresh install contains source watch templates, command, and skill.
- `docs update` restores missing source watch docs without touching runtime registry state.
- `connected-system doctor` reports missing providers.
- `watch-source doctor` reports missing cursor and dedupe configuration.
- `watch-source poll --dry-run` emits normalized source events without writing.
- `watch-source run-due --apply` writes local source event evidence and cursor state.
