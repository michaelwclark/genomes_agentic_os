# Holdout QA Results

Passed.

| Command Or Check | Exit | Result |
| --- | ---: | --- |
| `uv run --extra dev pytest -q` | 0 | `39 passed in 3.06s` |
| `agentic-os init --target <tmp-root>` | 0 | Runtime root created. |
| `agentic-os project create los losmon_replacement --repo <repo> --root <tmp-root>` | 0 | Project source-map repo ref created. |
| `agentic-os route "Deploy losmon_replacement to production" --root <tmp-root>` | 0 | Route packet included `losmon_replacement`. |
| `agentic-os context build --domain los --project losmon_replacement --root <tmp-root>` | 0 | Context packet included project source files. |
| `agentic-os here context build --root <tmp-root>` from linked repo | 0 | Context resolved the linked project. |
| Unknown route request | non-zero | Error contained `routing confidence is low`. |

Residual risk: the holdout validates deterministic local routing. It does not
validate remote repository availability beyond the source-map path existing.

