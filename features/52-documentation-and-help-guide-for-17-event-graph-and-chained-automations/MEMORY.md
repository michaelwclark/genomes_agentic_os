# Memory

Feature 17 event graph behavior is centered on
`src/genomes_agentic_os/event_graph.py`.

The runtime graph initializes under `shared_factory/00-control-plane/`, while
event envelopes, processing results, dead letters, and the ledger index live
under `shared_factory/06-runs-and-logs/events/`.
