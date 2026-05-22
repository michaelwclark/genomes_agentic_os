# Holdout QA

## Command Matrix

| Command Or Check | Purpose | Expected Result |
| --- | --- | --- |
| `uv run --extra dev pytest -q` | Repository regression suite | Passes |
| `agentic-os init --target <tmp-root>` | Create isolated runtime root | Root is created |
| `agentic-os docs install --root <tmp-root>` | Install source docs and plans into runtime | Missing assets are created |
| `agentic-os validate --root <tmp-root>` | Validate runtime structure | Reports valid root |
| `test -f <tmp-root>/shared_factory/05-knowledge/plans/README.md` | Confirm runtime plan index | File exists |
| `test -f <tmp-root>/shared_factory/05-knowledge/plans/00-current-state-and-gap-map.md` | Confirm source feature plan mirror | File exists |
| `test -f <tmp-root>/shared_factory/05-knowledge/plans/09-future-ideas-intake.md` | Confirm future-ideas plan mirror | File exists |
| `agentic-os docs update --root <tmp-root>` | Prove idempotent update path | Reports no changes |
| `agentic-os validate --root <tmp-root>` | Revalidate after update | Reports valid root |

## Non-Applicable Paths

- Dedicated `current-state` command: not applicable because feature 00 did not
  introduce a dedicated CLI command.
- Notion write checks: not applicable to feature 00 behavior; board write access
  is covered by Build Runner preflight.

