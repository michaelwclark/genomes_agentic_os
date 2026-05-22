# Holdout QA Results

Temp root: `/var/folders/n9/1qn8bnqn0vl70d18byskc4nr0000gn/T/agentic-os-feature51-POLINs/agentic_os`

| Step | Command | Result |
| --- | --- | --- |
| 1 | `uv run agentic-os init --target <temp-root>` | PASS, exit 0 |
| 2 | remove `commands/os-watch-source.md` and `templates/runtime/watch-source.yml` | PASS, files removed for repair check |
| 3 | `uv run agentic-os docs update --root <temp-root>` | PASS, exit 0; restored both managed files |
| 4 | `uv run agentic-os validate --root <temp-root>` | PASS, exit 0 |
| 5 | `uv run agentic-os connected-system list --root <temp-root>` | PASS, exit 0 |
| 6 | `uv run agentic-os connected-system doctor notion_genome --root <temp-root>` | PASS, exit 0 |
| 7 | `uv run agentic-os watch-source create agentic_os_kanban --root <temp-root> --external-ref database_id=366683b48dab81a1ab5fc73e7e1f5c60 --enabled` | PASS, exit 0 |
| 8 | `uv run agentic-os watch-source list --root <temp-root>` | PASS, exit 0 |
| 9 | `uv run agentic-os watch-source doctor agentic_os_kanban --root <temp-root>` | PASS, exit 0 |
| 10 | `uv run agentic-os watch-source poll agentic_os_kanban --root <temp-root> --dry-run` | PASS, exit 0 |
| 11 | `uv run agentic-os watch-source run-due --root <temp-root> --dry-run` | PASS, exit 0 |
| 12 | `uv run agentic-os watch-source poll agentic_os_kanban --root <temp-root> --apply` | PASS, exit 0; wrote one source event and cursor state |
| 13 | corrupt watch-source cursor and dedupe, then run `watch-source doctor` | PASS, expected exit 1 with missing cursor/dedupe findings |
| 14 | `uv run --extra dev pytest -q` | PASS, 39 passed in 2.95s |

Assertions:

- Restored watch-source command: yes.
- Restored watch-source runtime template: yes.
- Source event files written: 1.
- Cursor state includes `agentic_os_kanban`: yes.
- Negative doctor status: 1.
