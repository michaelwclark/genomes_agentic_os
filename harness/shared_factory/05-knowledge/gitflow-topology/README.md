# GitFlow Topology

This folder is the canonical F2 contract for resolving how one tracker item
maps to one or more pull-request targets. Project profiles and branch
registries provide data; consumers do not copy targeting policy.

## Loading Contract

1. Load `CONTRACT.md`.
2. Load the routed project's `project.yml` and its
   `dev_factory.pull_request.target_policy` block.
3. When `branch_registry` is configured, require a readable, current registry
   before release or hotfix writes.
4. Run `resolve_gitflow_targets.py` with the ticket snapshot and the exact set
   of currently open PR base branches.
5. Treat `required_targets`, `missing_targets`, `propagation`, and
   `family_complete` as the only topology verdict consumed by Auto-Dev,
   Auto-Dev Finalize, PR Review, and GitFlow PR Create.

## CLI

```bash
python3 harness/shared_factory/05-knowledge/gitflow-topology/resolve_gitflow_targets.py \
  --profile domains/los/02-projects/los_app_los_django/project.yml \
  --ticket ticket.json \
  --existing-target develop \
  --existing-target release/v10.0.0
```

The command prints deterministic JSON and performs no external writes.

## Validation

```bash
python3 -m unittest discover \
  -s harness/shared_factory/05-knowledge/gitflow-topology/tests \
  -p 'test_*.py'
```

Every fixture is self-contained. The required baseline covers a hotfix during
an active release, release targeting, develop-only work, and a missing family
target.
