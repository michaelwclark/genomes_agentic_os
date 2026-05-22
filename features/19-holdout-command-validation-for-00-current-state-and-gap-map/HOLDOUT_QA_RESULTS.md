# Holdout QA Results

Passed.

| Command Or Check | Exit | Result |
| --- | ---: | --- |
| `uv run --extra dev pytest -q` | 0 | `39 passed in 3.13s` |
| `uv run agentic-os init --target <tmp-root>` | 0 | Temporary OS root created. |
| `uv run agentic-os docs install --root <tmp-root>` | 0 | Runtime docs, templates, references, and plans created. |
| `uv run agentic-os validate --root <tmp-root>` | 0 | `valid: <tmp-root>` |
| `test -f <tmp-root>/shared_factory/05-knowledge/plans/README.md` | 0 | Plan index exists. |
| `test -f <tmp-root>/shared_factory/05-knowledge/plans/00-current-state-and-gap-map.md` | 0 | Feature 00 plan mirror exists. |
| `test -f <tmp-root>/shared_factory/05-knowledge/plans/09-future-ideas-intake.md` | 0 | Future ideas plan mirror exists. |
| `uv run agentic-os docs update --root <tmp-root>` | 0 | `no changes` on fresh docs install. |
| `uv run agentic-os validate --root <tmp-root>` | 0 | `valid: <tmp-root>` |

Residual risk: the validation proves file creation and structural validity, not
semantic freshness of every plan body after future backlog edits.

Docs alignment: observed behavior matches the feature 00 source artifacts and
the feature 18 guide path.

