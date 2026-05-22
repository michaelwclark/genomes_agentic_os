# Holdout QA

## Command Matrix

| Command Or Check | Expected Result |
| --- | --- |
| `uv run --extra dev pytest -q` | Repository suite passes. |
| `agentic-os init --target <tmp-root>` | Temporary OS root is created. |
| `agentic-os project create los losmon_replacement --repo <repo> --root <tmp-root>` | Project and source-map repo ref are created. |
| `agentic-os route "Deploy losmon_replacement to production" --root <tmp-root>` | Packet includes `losmon_replacement`. |
| `agentic-os context build --domain los --project losmon_replacement --root <tmp-root>` | Packet includes project source files. |
| `agentic-os here context build --root <tmp-root>` from linked repo | Packet resolves the linked project. |
| Unknown route request | Fails with low-confidence routing error. |

