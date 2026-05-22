# Spec

Validate feature 16, Connected Source Watch Registry, against the current
command surface.

Scope:

- Use a fresh temporary installed OS root.
- Confirm managed watch-source knowledge can be restored by `agentic-os docs update`.
- Validate connected-system registry commands.
- Validate watch-source create/list/doctor/poll/run-due/apply commands.
- Confirm apply mode writes local source events and cursor state.
- Confirm doctor catches malformed watch source state.
- Run the full source-package pytest suite.

Out of scope:

- Live external Notion reads.
- Provider-specific OAuth or connector setup.
- Changes to source implementation.

Acceptance criteria:

- The canonical Build Runner artifact set exists.
- Temp-root init succeeds.
- Removing `os-watch-source.md` and `templates/runtime/watch-source.yml`, then
  running docs update, restores both managed files.
- `validate`, `connected-system list`, and `connected-system doctor` pass.
- `watch-source create`, `list`, `doctor`, `poll --dry-run`, `run-due --dry-run`,
  and `poll --apply` pass.
- Apply mode writes a source event file and updates `watch-cursors.yml`.
- A malformed watch source fails doctor with missing cursor/dedupe findings.
- Full pytest passes from the worktree.
