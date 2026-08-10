# `/auto-dev-review-self-opposing-model`

Run the canonical opposing-model leg of Auto-Dev Review Self for one existing
Auto-Dev work item, for example:

```text
$auto-dev-review-self-opposing-model AGE-52
```

This command resolves the ticket's canonical work item, exact PR Create family,
current reviewed head, and configured review policy before it invokes the
selected opposing-model transport. It produces the review request, sanitized
model receipt, review ledger, and deterministic readiness decision consumed by
`$auto-dev-review-repair`. It never creates, retargets, pushes, merges, deploys,
or releases a pull request.

Use it from either Claude or Codex. Do not replace it with an ad-hoc `claude -p`
prompt, copied review text, or a different reviewer receipt format.
