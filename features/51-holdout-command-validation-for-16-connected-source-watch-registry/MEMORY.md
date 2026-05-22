# Memory

Feature 16 holdout confirms `watch-source poll --apply` writes local source
event files under `shared_factory/06-runs-and-logs/source-events/` and updates
cursor state in `shared_factory/00-control-plane/watch-cursors.yml`.

Malformed watch-source entries without cursor or dedupe metadata fail doctor.
