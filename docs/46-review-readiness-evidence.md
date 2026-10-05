# 46 · Review Readiness Evidence

Development Delivery owns a pinned gate contract and the execution receipts
that establish local validation. `review_readiness_evidence` projects those
receipts into packet-contained, content-addressed proof. The opposing review
runner consumes a fresh projection independently of reusable model findings.

A clean model review alone does not establish readiness. Missing command
receipts, incomplete provider pages, absent Copilot delivery, or changed branch
protection leave the corresponding gate unknown.

## Pinned policy

New policy resolutions emit `development-selected-profile/v2`. They freeze the
selected repository and target branch, complete validation configuration,
explicit `review.copilot.required`, and source/content hashes. The effective
policy fingerprint covers the selected profile. Version 1 snapshots remain
valid historical inputs; they are never rewritten or upgraded in place.

The selected repository's `validation.required_checks` must agree with its
`validation.ci_contract` (`github-required-check-contract/v1`). That contract
contains repository, target branch, required context/App-ID pairs, and provider
readback provenance: protection URL, capture timestamp, raw readback digest,
complete active branch rules, and the captured required pairs. Its drift policy
is `block_until_context_refresh`. Capture these from that repository's branch
protection and complete branch-rules readback. Another pipeline's check list
cannot provide authority.

The adapter compares the complete pinned contract with fresh protection/rules
readback on every projection, including cached model reuse. A newly required
context, removed context, changed App ID, target mismatch, or unreadable/stale
capture blocks CI proof. It requires every exact-head required context to have
a completed successful result from the specified App. Missing, skipped,
pending, cancelled, or failed results cannot pass. Legacy status contexts only
satisfy contracts that explicitly use App ID `-1`.

## Actual local execution

A terminal `development-stage-evidence/v1` local-validation receipt contains
`evidence.head_sha`, `evidence.policy_fingerprint`, and `evidence.validation_runs`:

```json
{
  "command": ".venv/bin/python -m pytest tests/ -q",
  "terminal": {"path": "artifacts/async-runs/full/terminal-receipt.json", "sha256": "<digest>"},
  "command_receipt": {"path": "artifacts/async-runs/full/command.json", "sha256": "<digest>"}
}
```

Each command and terminal file must be packet-contained and hash-bound. The
adapter validates the long-run terminal schema, run identity, exit status,
worktree, clean pre/post head, repository, and successful post-run invariants.
Every required logical command must have actual execution proof. Deferral to
CI remains unknown for local validation.

Command matching uses the frozen argument vector. Coverage and task-owned
pytest basetemp flags may extend it; focused selectors and additional test
paths cannot substitute for the required full suite. An alternate interpreter
needs explicit pinned authority, for example:

```yaml
validation:
  command_executables:
    '.venv/bin/python -m pytest tests/ -q':
      executable: '{work_item}/artifacts/test-runtime314/bin/python'
      authority: selected_profile
```

The resolved executable must remain within the canonical work item or
worktree. Interpreter version parity alone does not authorize substitution.
Record this mapping before the execution context is frozen; a mapping added
after a run cannot validate an old fingerprint.

## Provider proof and projection

The bounded GitHub adapter uses the existing `gh api` transport or an injected
provider callback. It reads the exact PR subject before and after collecting
branch protection, all active branch-rule pages, all check/status pages, all
review pages, and every GraphQL review-thread page. A changed head/base, failed
page, repeated cursor, resource bound, or capture older than five minutes leaves
provider proof unknown. It performs no model call or provider write.

Copilot must have delivered a completed review for the current head, with a
valid submitted timestamp, and complete thread readback. Zero threads with no
delivered review is unknown. Current unresolved threads or changes requested
block the gate. Exemption comes only from an explicit false requirement in the
pinned version 2 policy.

```bash
agentic-os develop readiness-proof /path/to/task/state.json \
  --head <exact-head> --provider-readback /path/to/packet/github-readback.json --json
```

The command exits zero only when all three proof gates pass. Canonical
implementation recording also emits local validation proof when its receipt
contains an exact head. Without provider input, CI and Copilot remain unknown.
The current envelope is `artifacts/finishing-touches/readiness-evidence.json`;
its validation/CI/Copilot/provider references point to immutable hashed leaves.
Later projections replace only the current envelope and preserve prior leaves.

## Integration and context refresh

`refresh_packet_readiness(packet, provider, head, policy)` is the required
opposing-runner hookup for both fresh and reused model receipts. It obtains new
provider readback and rewrites current proof; a cached successful capture never
substitutes for that call. The producer and consumer changes may be reviewed
separately, but acceptance requires an integrated candidate executing this hook
on both paths. Source tests and a draft PR do not establish installation or
customer-environment acceptance.

For legacy packets or protection drift, use a governed bounded context-refresh
or successor family that freezes the approved version 2 profile and current
contract. Preserve the predecessor snapshot and fingerprint. Re-run final-head
validation against the successor policy and record real command bindings;
never patch old policy bytes or relabel old receipts. The canonical
validation-refresh owner must emit proof after recording successor evidence.
Keep installed configuration changes as a proposal until integrated proof and
ongoing frozen contexts are protected.

The execution command must record `REVIEW_POLICY_FINGERPRINT=<pinned hash>` in
its actual `env` argument vector. An inherited variable or an unused metadata
field does not establish this binding. Both command and terminal receipts must
record `expected_git_identity.worktree` equal to the canonical registered
worktree; the command's `work_dir` must match it exactly. The actual pre/post
Git identities use the existing producer shape: a nonempty matching provider
repository URL, exact registered branch, exact head, and clean status. Repository
aliases or filesystem Git paths that cannot establish provider identity remain
unknown.
