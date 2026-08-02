# GitFlow contract

- **Owner:** Agentic OS maintainers
- **Applies to:** `genomes_agentic_os`, `genomes_agentic_harness`,
  `genomes_agentic_lib`, and `genomes_agentic_brain` only
- **Status:** canonical branch-topology policy

This contract defines the shared GitFlow roles for the four Agentic OS source
repositories. It does not change a repository's default branch or branch
protections, and it does not authorize a release or hotfix by itself.

## Long-lived branches

Each repository has a `main` and a `develop` branch. Normal feature and fix
pull requests target `develop`. `main` receives reviewed release promotions and
hotfixes only. A repository may have additional local validation requirements,
but it must not replace these branch roles.

| Repository | Integration branch | Release branch |
| --- | --- | --- |
| `genomes_agentic_os` | `develop` | `main` |
| `genomes_agentic_harness` | `develop` | `main` |
| `genomes_agentic_lib` | `develop` | `main` |
| `genomes_agentic_brain` | `develop` | `main` |

`genomes_agentic_platform` is not part of this contract.

## Release branches

Create a short-lived `release/vX.Y.Z` branch only when an approved release
needs a stabilization lane. Create it from the selected `develop` SHA, allow
only release-stabilizing changes, and promote it to `main` through a reviewed
pull request after the repository's required checks pass. Every stabilization
change must also return to `develop`; do not leave release-only fixes behind.

No release branch is created automatically, and a branch name alone is not a
release authorization.

## Hotfix branches

Create a short-lived `hotfix/vX.Y.Z` branch only for an approved production
repair. Start it from the affected release tag or `main` SHA, promote the fix
to `main` through a reviewed pull request, then forward-port the exact fix to
`develop`. The repair is not complete until both target branches contain it.

No hotfix branch is created automatically. A hotfix never bypasses required
checks, review, release evidence, or provider readback.

## Required receipts

Before creating a branch or pull request, read the exact provider base SHA.
Before merge, read back the head SHA, target branch, checks, reviews, and merge
state. Record the source SHA for every `develop`, `release/*`, and `hotfix/*`
branch creation. Do not use local checkout state as proof of remote topology.
