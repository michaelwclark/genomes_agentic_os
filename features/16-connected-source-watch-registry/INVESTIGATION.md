# Investigation

The current installer already copies `templates/`, `harness/commands/`, and `harness/skills/` into runtime knowledge, so this feature could use the existing docs update mechanism.

The missing piece was runtime state. The implementation adds additive local registries under `shared_factory/00-control-plane/` only when source-watch commands run. This keeps `docs update` from overwriting active customer or Genome watcher state.
