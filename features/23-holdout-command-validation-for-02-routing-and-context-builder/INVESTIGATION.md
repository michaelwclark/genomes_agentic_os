# Investigation

Feature 02 routing depends on runtime filesystem state, not remote services.
The holdout needs a disposable OS root, a linked repository path in the project
source map, and a request containing the known project slug.

Relevant commands:

- `agentic-os route`
- `agentic-os context build`
- `agentic-os here context build`

Relevant source files:

- `src/genomes_agentic_os/routing.py`
- `src/genomes_agentic_os/cli.py`
- `tests/test_cli_scaffold.py`
- `features/02-routing-and-context-builder/`

