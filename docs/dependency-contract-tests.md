# Dependency Contract Tests

Every third-party dependency in this repo has a contract test asserting the
exact API surface this project uses: imports resolve, the functions and
classes we call exist, and our call shapes still work. Contract tests are the
upgrade safety net: when Renovate bumps a dependency and its API surface
changed, the contract test fails even if no other test catches it.

## The rule

When adding a new dependency:

1. **Python** (`pyproject.toml`): create
   `tests/contracts/test_<normalized_name>_contract.py` (lowercase, `-`/`.`
   replaced with `_`, e.g. `graphql-core` -> `test_graphql_core_contract.py`),
   or add the package to `EXCLUDED` in
   `tests/contracts/test_contract_coverage.py` with a reason.
2. **GUI** (`apps/agentic-os-gui/package.json`): create
   `apps/agentic-os-gui/e2e/contracts/<package-name>.contract.ts`
   (`@scope/name` -> `scope-name.contract.ts`), or add the package to
   `EXCLUDED` in `apps/agentic-os-gui/scripts/check-contract-coverage.mjs`
   with a comment saying why.

Only tooling-only packages with no importable runtime surface may be excluded
(type definition packages, CLI-only packagers, build backends). Anything the
source imports must have a contract.

Contract tests assert what *this project* uses — derive assertions from actual
imports and call sites, prefer cheap real invocations over bare `typeof`
checks, and do not contract API surface we never touch.

## Commands

Python (contracts live under `tests/`, so the normal suite already includes them):

```bash
python -m pytest tests/contracts -q   # contracts only
python -m pytest tests/ -q            # full suite (what CI runs)
```

GUI (from `apps/agentic-os-gui/`):

```bash
pnpm test:contracts            # run the contract suite
pnpm check:contracts-coverage  # verify every dependency is covered or excluded
```

CI runs both surfaces on every PR (`.github/workflows/test.yml`: `pytest` and
`gui` jobs), so a Renovate PR gets contract verdicts automatically.

## How the auto-merge automation consumes this

Renovate opens dependency PRs one at a time (`renovate.json`:
`prConcurrentLimit: 1`, `rebaseWhen: behind-base-branch`, `automerge: false` —
Renovate itself never merges).

- **Green checks** on a Renovate PR mean our recorded usage of the bumped
  package still works, so the dependency-update automation may merge it
  without human review.
- **Red contract tests** mean the upgrade changed API surface we depend on:
  an agent updates our usage and the contract tests together on the Renovate
  branch, and only then is the PR mergeable.

The contract suites are only as strong as their coverage — the coverage
checkers fail CI when a dependency has neither a contract nor a justified
exclusion, so the safety net cannot silently rot.
