# `/auto-dev-review-self-opposing-model`

Run or reuse the stable-keyed canonical full review owned by Review Self, or a
delta explicitly requested by Review Repair, for one work item:

```text
$auto-dev-review-self-opposing-model AGE-52
```

This command resolves the ticket's canonical work item, exact PR Create family,
current reviewed head, and configured review policy before it claims the review
key and invokes the selected opposing-model transport. It produces the review request, sanitized
model receipt, review ledger, and deterministic readiness decision consumed by
`$auto-dev-review-repair`. Repeated or concurrent exact-key calls reuse/join;
provider output is one consolidated terminal marked comment. It never creates,
retargets, pushes, merges, deploys, or releases a pull request.

New native Claude calls use schema-constrained JSON output with strict success
envelope and verdict/findings validation. Original stdout bytes and their hash
are preserved separately from the deterministic ledger projection. Historical
text responses remain immutable evidence. Protocol recovery keeps the same
subject and shared coordinator, allocates new attempt artifacts, and requires
one guarded acceptance call after local validation. See the skill's bounded
recovery contract; source validation alone does not establish review authority.

Use it from either Claude or Codex. Do not replace it with an ad-hoc `claude -p`
prompt, copied review text, or a different reviewer receipt format.
