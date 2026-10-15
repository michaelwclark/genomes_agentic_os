# Immutable authority for required PR-family targets

A canonical delivery task keeps one primary repository, base, PR and reviewed
revision. Its ordinary Finalize receipt authorizes exactly that primary. A
required sibling with a different base or head must have its own immutable
decision. Neither a family list nor a relabeled primary descriptor supplies it.

`auto-dev family-target` consumes the existing active typed
`release_propagation` family. It never creates a tracker task, changes the
primary subject, calls a review model, merges a PR or deploys anything.

## Record and validate

```sh
agentic-os auto-dev family-target finalize /path/to/packet/autodev.json \
  --evidence /path/to/packet/artifacts/sibling-finalize.json \
  --idempotency-key ticket:sibling:finalize --json

agentic-os auto-dev family-target validate /path/to/packet/autodev.json \
  --authority /path/to/saved-authority-descriptor.json \
  --provider github --repository github:owner/repository \
  --pull-request github:owner/repository#42 --base-branch main \
  --subject-revision <full-source-sha> --author-identity github:author \
  --author-kind ours --json
```

Finalize takes ordinary `auto-dev-stage-evidence/v1`, stage `finalize`, status
`completed`, summary, verified timestamp and exact `subject_revision`. Its
structured `evidence` contains:

- `provider`, `repository`, `pull_request`, `base_branch`, `base_sha`,
  `source_branch`, `author_identity`, `author_kind`, `readback_verified: true`,
  `readiness_decision: ready_for_merge`, and `readiness_scope: source`.
- `source_scope`: the registered `worktree`, exact `tree_sha`, and
  `full_diff_sha256` of `git diff --binary <direct-base> <source-head> --`.
  The tracked source must be clean and the origin must match the canonical
  selected repository or its previously accepted current-catalog provenance.
- `canonical_review`: a `{ref, sha256}` descriptor for the actual canonical
  receipt, and its explicit `review_policy_fingerprint`. The loader validates
  clean outcome, full PR/base/head/purpose/policy scope and inherited review
  authority. It does not reinterpret an unavailable or findings outcome.
  The explicit target policy must equal either the original frozen task policy
  or the historical canonical policy already accepted in the immutable primary
  readiness receipt. A sibling does not inherit the primary's policy by default.
  Both source authorities and their raw hashes remain bound in the decision.
- `provider_readback`, `acceptance`, `qa`, `secondary_review`, and
  `release_validation`: exact `{ref, sha256}` descriptors.

Acceptance, QA and secondary evidence use typed stage evidence and qualify
the sibling revision, repository, PR, base branch and base SHA. Each contains
nonempty `evidence.receipt_refs` as `{ref, sha256}` descriptors for actual
proof. Release validation is the sibling's own completed
`validate_production_release` evidence, with the same exact authority and the
existing required matrices and check IDs, all passing. Its proofs are also
hashed. These source decisions do not assert distribution or live acceptance.
Each proof has its exact stage: acceptance `document`, QA `qa`, secondary
`review_self`, and release validation `validate_production_release`. All required
QA/contract/runtime/provider references and each release matrix evidence reference
are individually hash-checked; an unrelated immutable document cannot substitute.

Provider readback contains `observed_at`, `readback_verified: true`, `pr` and
complete `review_threads`. `pr` retains the actual GitHub JSON fields `number`,
`url`, `baseRefName`, `baseRefOid`, `headRefName`, `headRefOid`, `state`,
`isDraft`, `author.login`, `mergeable` and `statusCheckRollup`. Threads contain
`nodes` and `pageInfo.hasNextPage: false`; every current thread must be resolved
or outdated. Unknown mergeability, pending/failed checks and unqualified skips
refuse readiness. Provider observations expire after ten minutes.
The registered accepted primary checkout may prove a sibling release ref only
when both refs have that exact accepted source head. Its path and checkout branch
must still equal the accepted primary worktree; fresh provider readback separately
proves the sibling's real release ref. Other same-head or detached checkouts do
not substitute. The complete direct-base binary diff remains mandatory even when
the reviewed main base is not an ancestor of the source head.
Every applicable static PR workflow job is derived from the exact source and
must appear in the provider results. A single green check cannot hide an omitted
required job. Readback also includes the complete actual Actions `workflow_runs`
response (`complete: true`, `total_count`, `workflow_runs`) and `workflow_jobs`,
keyed by run ID with each complete `total_count`/`jobs` response. Each required
workflow must have a successful latest `pull_request` run for the exact source
repository, PR number, source head and reviewed base. Each required completed
job must bind its actual run ID, head SHA and job URL to the current PR check's
`detailsUrl` and result. Green push jobs with the same names cannot substitute
for missing or pending PR jobs. Dynamic jobs, path filters, wildcard branch filters and
`pull_request_target` workflows require an explicit future inventory adapter;
they fail closed in this bounded GitHub implementation.

The one supported intentional skip is the source-proven main exclusion
`github.event_name == 'pull_request' && github.base_ref != 'main'`.
`allowed_skips` entries name the check, reason and hashed proof. The proof uses
`auto-dev-ci-applicability/v1`, event `pull_request`, exact `base_branch` and
`subject_revision`, status `not_applicable`, `workflow_path`, `job_id` and exact
`condition`. The tool reads that job's name and condition from the actual
source commit. Other conditional skips require an explicit future adapter.

The returned descriptor points to an immutable
`auto-dev-family-target-finalize/v1` receipt and binds `owner:
family_target_finalize`, `target_key`, raw digest and exact authority. Save the
descriptor without editing it. The ordinary primary merge validator also
requires every required sibling decision when a typed multi-PR family exists.
All unmerged members require current observations before either first merge.
After a member has merged, its immutable native provider merge evidence proves
that completed counterpart; it need not pretend to remain open. An actual
primary `merged` transition preserves the sibling's original source authority.

## Record the actual sibling merge

After the authorized provider merge and readback:

```sh
agentic-os auto-dev family-target merge-readback /path/to/packet/autodev.json \
  --evidence /path/to/packet/artifacts/sibling-merged.json \
  --idempotency-key ticket:sibling:merged --json
```

Input is `development-stage-evidence/v1`, state `merged`, status `completed`,
with summary, verified timestamp and structured evidence containing the same
exact target, `source_head_sha`, provider `merge_sha`, `readback_verified:
true`, `readiness_authority` and a fresh hashed `provider_readback`. The actual
PR must be `MERGED`, with `mergeCommit.oid` and `mergedAt`. Its base branch is
still checked; its post-merge base tip may have advanced to the merge commit.

The recorder appends an immutable `auto-dev-family-target-merge/v1` receipt and
an entry in the linked task's `family_merges`. It preserves the primary task's
state, reviewed revision, stage receipts and terminal merge authority. Exact
retries reuse the same bytes. Contradictory retries and changed proof fail
before a dependent mutation.

## Control-flow contract

| Operation/precondition | Signal | Permitted effect |
| --- | --- | --- |
| Finalize, exact required own sibling and complete current proof | Exact immutable authority descriptor | Target receipt and separate target projection |
| Finalize, identical current retry | Same descriptor | No different receipt or primary state |
| Validate, exact recorded authority and complete required family | Same descriptor | Read only |
| Merge readback, exact authority and actual provider merge | Immutable merge ref/digest | Separate family merge ledger only |
| Merge readback, identical retry | Same merge ref/digest | No different receipt or primary state |
| Wrong target/base/head/author/policy or unqualified review | `AutoDevStateError`, CLI exit 2 | None |
| Stale/failed provider state, pending checks or unresolved threads | `AutoDevStateError`, CLI exit 2 | None |
| Missing family decision, predecessor or frozen authority | `AutoDevStateError`, CLI exit 2 | None |
| Altered wrapper, nested proof or conflicting idempotency key | `AutoDevStateError`, CLI exit 2 | None |

Use the ordinary primary stage recorder for the primary. Do not retarget its
descriptor, clone its task into a sibling, reset its lifecycle for alias
normalization, rewrite a canonical receipt, or infer live qualification from
these source receipts.
