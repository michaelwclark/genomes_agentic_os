# Auto-Dev: release propagation

This is a compatibility policy note. `/auto-dev-release-propagation` delegates
to `/auto-dev-pr-create` family mode. The canonical PR Create policy selects
targets, creates or reuses PRs, and records family completeness; this file must
not introduce a second targeting or provider contract.

## Inputs

- live tracker release/fix-version authority and project GitFlow topology;
- exact source revision and original pull request;
- required target branches/repositories and their current heads;
- project rules for merge-up, backport, forward-port, cherry-pick, migration
  order, generated files, version metadata, and sibling pull requests;
- effective review, QA, and artifact policy.

Never infer propagation solely from branch names or copy an old ticket's pull
request pattern. If ticket/release authority is missing or contradictory, stop
with the exact question.

## Propagation behavior

1. Resolve the complete expected target set and order before creating branches.
2. Verify each target exists, is the configured repository/base, and does not
   already contain the change or an equivalent provider-verified pull request.
3. Use the project-owned propagation method. Preserve the intended behavior;
   do not blindly transplant code that has different APIs or schema on the
   target branch.
4. Resolve conflicts deliberately and record target-specific changes.
5. Inspect migration numbering/dependencies, package locks, generated outputs,
   configuration, feature flags, and release metadata separately for each
   target.
6. Run the target branch's required focused tests and quality gates.
7. Create or update each pull request through Create Artifacts with the correct
   tracker linkage, source/target, relationship, test evidence, and propagation
   notes.
8. Read every pull request back from the provider and record exact head/base,
   checks, and sibling relationships.

Parallel target work is allowed only when the branches and files are isolated
and project ordering does not create dependencies. The coordinator reconciles
the family and ensures later targets are based on the intended revision.

## Done criteria

Propagation evidence lists the authoritative reason, method, source revision,
expected targets, created/existing pull requests, target-specific revisions,
conflicts, migrations/dependencies, tests, and provider readbacks.

The PR Create boundary completes when every required target has a verified pull
request or a typed policy-backed `not_required` disposition. A created branch,
local cherry-pick, or unverified URL is not enough. This compatibility flow
does not approve or merge pull requests; Review Self, Finalize, and Merge
retain those authorities.
