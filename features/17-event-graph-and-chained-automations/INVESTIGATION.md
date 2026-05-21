# Investigation

The existing `run-log close` command already records validation-backed closeout evidence. Feature 17 extends that path by optionally emitting a normalized event after closeout, while keeping the closeout write itself unchanged.

The event graph uses local files under `shared_factory/00-control-plane/` and `shared_factory/06-runs-and-logs/events/`. This preserves the current filesystem source-of-truth model and leaves room for a future active state plane.
