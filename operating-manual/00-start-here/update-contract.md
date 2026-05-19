# Update Contract

The installed OS is live runtime state. Treat it like a working directory with human and agent edits, not a disposable build artifact.

## Rule

Install and update commands are non-destructive, additive, and idempotent.

## Allowed By Default

- Create missing folders.
- Create missing files.
- Add newly packaged manual pages, command prompts, skill specs, templates, examples, diagrams, schemas, and validators.
- Re-run safely without changing existing files.

## Not Allowed By Default

- Overwrite existing files.
- Rewrite local edits.
- Delete runtime files.
- Move active work.
- Archive work without explicit approval.

## Existing File Changes

If a packaged template or manual page needs to change an existing installed file, use a future explicit migration flow with:

- previewable diff,
- reason for the change,
- files affected,
- rollback path,
- human approval.
