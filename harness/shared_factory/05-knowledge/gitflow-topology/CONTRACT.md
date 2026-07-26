# GitFlow PR Topology Contract

## Purpose

Resolve a ticket, project delivery profile, and optional live branch registry
into one canonical PR-family verdict. This contract owns target selection and
family completeness. Project files contain only project-specific data.

## Inputs

- `project.yml`: `dev_factory.pull_request.target_policy` plus repository
  defaults.
- Ticket snapshot: key, type, fix version, labels, and an optional explicit
  `topology_class` or `route`.
- Branch registry: current branch aliases and optional targeting rules.
- Existing PR targets: base branches already represented by open PRs.

## Supported Profiles

- `registry_gitflow`: resolve release and hotfix aliases from a live registry;
  LOS is the first binding.
- `promote`: implementation targets the configured development branch and a
  separate release workflow promotes it to the production branch; Kanga uses
  `develop` then `main`.
- `continuous_delivery`: ticket PRs target the configured default branch and
  release immediately after the family merge gate.

## Route Resolution

Explicit `topology_class` or `route` wins. Otherwise:

1. Hotfix type, label, or the registry's next-hotfix fix version selects
   `hotfix`.
2. Regression type or label selects `regression`.
3. A fix version matching the active release or configured release prefixes
   selects `release`.
4. Everything else selects `default`.

For `registry_gitflow`, the registry's `targeting_rules` are preferred when a
matching route is present. The project policy remains the compatibility input
for `release_targets` and `hotfix_with_active_release_targets`.

## Output

The resolver emits:

- `route` and `profile`;
- ordered `required_targets`, each with its symbolic role and resolved branch;
- `existing_targets`, `missing_targets`, and `unexpected_targets`;
- `family_complete` (`null` until an existing-target set is supplied);
- `propagation` (`cherry_pick`, `merge`, or `none`);
- `release` metadata describing immediate vs deferred delivery;
- `blockers` for unresolved aliases or missing required branches.

Consumers must not infer additional targets after this verdict. A missing
required target blocks ready-for-merge unless an operator decision is recorded
in the work-item packet.

## Ownership And Consumers

- Auto-Dev calls the resolver before PR creation.
- Auto-Dev Finalize calls it during Phase 0 and uses its family-completeness
  verdict.
- PR Review reports missing target coverage as a finding.
- GitFlow PR Create opens only the missing targets returned by the resolver.
- Trigger adapters may invoke these consumers but carry no topology policy.

## Safety

- The resolver is read-only and deterministic for identical inputs.
- Runtime release/hotfix writes require the routed registry freshness gate.
- Branch aliases that cannot be resolved fail closed.
- Project-specific branch names and release behavior stay in project config or
  branch-registry state, not in this contract or consumer skills.
