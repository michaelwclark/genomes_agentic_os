# Branch and Pull Request Rules

- Resolve the exact configured base branch and remote SHA before creating a
  task branch. Never infer `main`, `develop`, or a release branch.
- One task owns one isolated worktree per repository/target branch. Do not edit
  shared checkouts or reuse a branch with ambiguous ownership.
- PR Create resolves the complete project target matrix and creates or reuses
  every required primary, release, hotfix, backport, or forward-port pull
  request while preserving links to the source task and commit.
- Do not force-push, bypass hooks, auto-merge, or invent release scope without
  explicit policy and authorization.
- Merge readiness requires fresh readback of checks, reviews, target branch,
  head SHA, and configured release obligations.
