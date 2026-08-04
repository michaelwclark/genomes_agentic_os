# SemVer release dry run

Agentic OS derives, but does not publish, a SemVer candidate whenever a pull
request is merged into `release/*`. The workflow checks out the merge commit,
finds the nearest reachable `vX.Y.Z` tag, and evaluates all Conventional Commits
between that tag and the merge commit.

`feat` produces a minor candidate; `fix` and `perf` produce a patch candidate;
and a breaking change produces a major candidate. While the project remains at
major zero, a breaking change increments the minor version, matching the pinned
Commitizen policy. Other commit types produce no release candidate.

The derived candidate must equal `[project].version` in `pyproject.toml`. A
mismatch fails the dry run before a tag, GitHub release, package, container, or
other provider state can be created. The existing tag-triggered Release workflow
remains the publication path and continues to validate the tag against that same
project version.

This workflow has read-only contents permission. Creating a tag or GitHub
release remains a separately approved provider operation after release checks,
assets, and the existing release contract have passed.
