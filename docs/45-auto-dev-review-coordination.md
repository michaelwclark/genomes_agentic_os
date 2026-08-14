# 45 · Auto-Dev Review Coordination

Last updated: 2026-08-14

> **Snapshot:** Auto-Dev pays for one review of one exact subject, reuses that
> result everywhere it remains valid, and blocks before another model or
> provider call would exceed policy.

## What is this?

Review coordination is the single-flight and receipt contract shared by Review
Self, Review Repair, opposing-model review, and Finalize. It prevents a stage
boundary, retry, second harness, or changed reviewer identity from turning the
same pull-request head into another full review.

The source of truth is `src/genomes_agentic_os/review_coordination.py`, with the
wire contract in `schemas/auto-dev-review-receipt.schema.json`. Harness skills
consume that contract; they do not invent separate review state.

## When should it run?

Run coordination before every paid reviewer invocation and before every
provider-visible review post. Finalize also runs it, but Finalize only validates
and reuses an exact-head terminal receipt. It does not invoke another reviewer.

## What happens when it runs?

The coordinator derives a stable review key from:

- provider-qualified repository and pull-request identity;
- exact head revision and base revision;
- effective policy fingerprint;
- normalized review scope and purpose.

Reviewer or model identity is deliberately not in the key. Changing models
cannot bypass deduplication. Under the per-key lock, the coordinator chooses one
action:

| Action | Meaning |
| --- | --- |
| `reuse` | A terminal receipt for this exact key already exists. Return it with zero model calls. |
| `join` | Another process owns the same in-flight key. Wait for that owner, then reuse its terminal receipt. |
| `delta` | The head changed after repair, while repository, PR, base, policy, scope, and purpose remain in the same review chain. Review only the new diff and unresolved findings. |
| `full` | No reusable chain exists, or an authorized base/policy invalidation starts a new chain. |
| `block` | A budget, lineage, exact-head, receipt-integrity, or provider-post guard fails before an external call. |

One full review establishes the chain. Repair creates a changed-head delta whose
parent is the prior terminal receipt. A delta carries the normalized finding
ledger forward: stable finding id, first-seen head, latest-seen head, status,
severity, evidence, and resolution reference. Resolved findings stay in the
ledger as resolved; they are not rediscovered and rewritten as new prose.

## Where does it live, and where is its output?

The delivery packet chooses the receipt root. Each stable key owns one immutable
terminal JSON receipt and a lock beside it. Family and chain hashes let the
coordinator count prior work without rereading or reposting whole reviews.

Provider output is separate from the local evidence. At most one terminal
provider post is allowed for the PR family. The post includes the hidden marker
`<!-- agentic-os-review:<stable-key> -->`; provider readback must confirm that
marker before the post is considered complete. Intermediate retries and
in-flight findings remain local.

## How is it configured?

The default circuit-breaker budget is intentionally small:

| Budget | Default |
| --- | ---: |
| full reviews per base/policy chain | 1 |
| changed-head delta reviews per chain | 3 |
| absolute full reviews per PR family | 2 |
| terminal provider posts per PR family | 1 |

These are the `1/3/2/1` limits. Domain policy may lower them. Increasing a limit
is an explicit recovery action: record the operator, reason, prior receipt,
requested limit, expiry, and a new policy fingerprint. Never delete receipts,
change reviewer identity, or restart Auto-Dev to manufacture a fresh budget.

## Invalidation, recovery, and override

A head-only change keeps the chain and permits a delta. Base revision, policy
fingerprint, normalized scope, or purpose drift invalidates chain reuse and may
permit one new full review, subject to the absolute family limit. Repository or
PR identity drift is a different family and must not consume the old receipt.

If a reviewer becomes unavailable, record terminal `unavailable` evidence and
resume the same key. If a process dies while owning a lock, recover the same
receipt path after verifying ownership and exact provider head. If a receipt is
malformed or its subject does not match, quarantine it and block; do not accept
it as clean. Emergency budget overrides are narrow, expiring policy changes,
not command-line force flags.

Before any provider post, read the head again. If it changed during review,
write no provider comment and route the new head through delta coordination.
Before Finalize, read the head again and require the same terminal receipt key,
subject revision, base, policy fingerprint, and terminal outcome. Finalize
reuse therefore makes zero model calls and zero duplicate provider posts.

## Metrics and operating signals

Emit compact counters from receipts, not copied review bodies:

- reviewer invocations by `full` and `delta`;
- exact-key reuses and concurrent joins;
- duplicate invocations prevented;
- full/delta/family budget used and blocked attempts;
- provider posts attempted, reused by marker, and completed;
- review-to-terminal latency and tokens/cost when the provider supplies them;
- open, resolved, and regressed finding counts.

A healthy run has one terminal receipt per stable key, a monotonic finding
ledger, no budget overflow, and zero Finalize reviewer invocations.

## Installing a released local runtime

macOS operators activate the released wheel with the guarded installer. It
requires a trusted SHA-256 unless an explicit recovery override is supplied,
installs a non-editable versioned virtual environment, validates package and
CLI readback, retains both rollback targets, and atomically switches the two
dispatcher aliases.

```bash
python scripts/release/install-local-release-runtime.py \
  --wheel /path/to/genomes_agentic_os-X.Y.Z-py3-none-any.whl \
  --sha256-file /path/to/SHA256SUMS \
  --release-revision <merged-release-sha> \
  --receipt /path/to/deployment-readback.json \
  --apply
```

The receipt records prior and new alias targets, wheel checksum, installed
package/version/module path, smoke result, exact release revision, rollback
pointers, and `readback_verified`. The installer refuses to overwrite an
existing versioned runtime or replace a non-symlink alias. Roll back by
atomically switching each active alias to its recorded `.previous` target, then
read back package version, module path, and `agentic-os --help` again.

## What else is important?

Exact-head safety outranks a clean-looking review. A clean receipt for an old
head is historical evidence, not merge authorization. Keep provider prose
short and terminal; the local receipt and finding ledger are the audit source.
This contract coordinates reviewers across Claude, Codex, retries, and Auto-Dev
stages without asking any of them to reread the full review.

