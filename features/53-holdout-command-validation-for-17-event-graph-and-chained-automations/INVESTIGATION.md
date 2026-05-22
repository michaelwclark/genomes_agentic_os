# Investigation

Feature 17 exposes file-backed event graph operations through
`agentic-os event` and `agentic-os chain`.

The relevant implementation is `src/genomes_agentic_os/event_graph.py`.
Runtime state lives under `shared_factory/00-control-plane/` and event records
live under `shared_factory/06-runs-and-logs/events/`.

The holdout exercised the public CLI surface rather than internal Python
helpers.
