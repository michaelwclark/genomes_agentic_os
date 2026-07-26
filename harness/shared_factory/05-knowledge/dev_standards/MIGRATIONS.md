# Migrations And Data Changes

Focus: branch-correct migration graphs and rolling-deploy-safe schema changes.

## Write
- Additive-first, reversible when feasible; schema and data changes separated
  unless atomically required.
- Dependencies point at the TARGET branch's migration leaf; numbering does
  not collide on the target branch; destructive changes ship behind a
  verified backfill and a plan.

## Review
- Static graph check per target branch: every dependency exists there;
  cherry-picks repointed to the target leaf, filename kept, never renumbered
  after push.
- Rolling-deploy safety: old code must run against the new schema during
  deploy.

Blocking: always.
