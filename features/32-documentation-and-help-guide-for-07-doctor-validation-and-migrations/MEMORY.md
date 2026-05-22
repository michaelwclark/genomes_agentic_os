# Memory

The doctor guide should emphasize that `--fix-missing` is additive only. It does
not close run logs, decide project state, or overwrite local edits.

The current migration ID is `notion-sync-readme-v1`, and apply must fail if the
target changed after the saved preview.
