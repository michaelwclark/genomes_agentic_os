# Auto-Dev: merge

Use `/auto-dev-merge` for the governed provider mutation that merges one exact
pull request. Merge is deliberately separate from review and Finalize so clean
code is not mistaken for mutation authority.

## Required authority

For an agent-authored pull request, require the immutable completed Finalize
receipt with `author_kind: ours` and
`readiness_decision: ready_for_merge`. For another author's pull request,
require the canonical completed Review Others receipt with
`author_kind: others`, `review_mode: review_no_merge`, and
`review_result: clean`.

The hashed authority must match the same provider, pull request, configured
repository, base branch, reviewed revision, and provider-read author identity.
A caller-supplied SHA, local branch, pasted review result, or nearby green check
is not authority.

## Immediate preflight

Just before mutation:

1. verify the exact provider account, repository, pull request, source, target,
   author, and expected merge method;
2. re-read the live source head and require it to equal the reviewed
   `subject_revision`;
3. re-read required checks, reviews, conversations, mergeability, branch
   protection, and policy gates;
4. verify any required sibling sequencing, propagation, migration/dependency
   order, release boundary, and human approval;
5. stop if the pull request changed, is already closed unexpectedly, targets a
   different branch, or lacks current authority.

Do not resolve uncertainty by force pushing, bypassing protection, changing the
base, using administrator override, or switching merge method unless the routed
policy and explicit approval authorize that exact action.

## Mutation and readback

Execute only the configured provider merge. Then read the pull request back
from the provider and write completed `development-stage-evidence/v1` containing
at least:

- `merge_sha` and provider-read `source_head_sha`;
- `provider`, `pull_request`, configured `repository`, and configured
  `base_branch`;
- provider-qualified `author_identity` and derived `author_kind`;
- the hashed owner receipt and exact reviewed `subject_revision`;
- merge method/time and `readback_verified: true`.

The provider/PR/repository/base/revision/author chain in open, readiness, and
merged readbacks must match. A successful mutation response without matching
live readback is not a completed merge.

Health later uses this authority without translation:
`terminal_authority.provider` equals `evidence.provider`,
`terminal_authority.ref` equals `evidence.pull_request`, and the terminal
revision equals `evidence.merge_sha`. See
`examples/auto-dev-merge-evidence.json` for a schema-valid field guide.

## Done criteria

Merge completes only after provider readback proves the expected pull request
merged at the exact `merge_sha` and the typed receipt is stored in the packet.
It does not imply release, deployment, tracker closeout, or cleanup.
