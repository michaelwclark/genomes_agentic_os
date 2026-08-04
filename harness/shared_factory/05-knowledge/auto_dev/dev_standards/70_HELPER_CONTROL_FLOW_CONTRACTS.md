# Helper Control-Flow Contracts

Apply this standard whenever a helper's return value, standard output, exit
status, exception, or persisted status controls a production branch. Treat
that signal as a public control-flow contract, even when the helper is local or
the current caller is its only consumer.

## Required semantic contract

- Define every semantic outcome before implementation. For each outcome,
  specify the exact returned value or output token, exit status or exception,
  caller branch, allowed side effects, and operator-visible evidence.
- Keep machine-readable control output separate from diagnostic output. A
  caller must not infer state from human prose, substring matching, log order,
  an empty value, or an incidental command status.
- Give every successful state an explicit, unambiguous signal. Do not collapse
  distinct success states such as `present`, `absent`, `reused`, and `created`
  unless the caller's behavior is intentionally identical for all of them.
- Define failure as a first-class outcome. Validation, lookup, parsing, and
  dependency failures must reach a failure branch before any mutation that
  depends on their result.
- Keep names, comments, help text, and tests aligned with the actual contract.
  A comment that says a helper verifies one state may not remain above code
  that verifies a broader, narrower, or different state.

## Complete behavior matrix

Before changing the helper or any caller, enumerate the complete matrix. At a
minimum, record these columns:

| Input or precondition | Existing state | Requested action | Exact helper signal | Caller branch | Allowed side effect | Required evidence |
| --- | --- | --- | --- | --- | --- | --- |

Include every accepted input, every relevant existing state, every requested
action, every successful helper output, and every failure that can occur before
a side effect. Include combinations that should deliberately refuse or do
nothing. If two cells intentionally converge, state why; do not omit one.

The matrix is incomplete when it covers only the repaired example, only the
happy path, or only the helper without the production caller that consumes its
signal.

## Implementation checklist

- Locate every production consumer of the helper signal and confirm that each
  interprets the same contract.
- Implement one canonical helper rather than duplicating its logic in callers,
  fixtures, or tests.
- Use exact typed values or stable tokens for semantic outcomes. Reserve
  non-zero status or exceptions for failures unless the documented interface
  explicitly defines another convention.
- Order guards so an error is detected before the first dependent side effect.
  Do not require prerequisites for branches that do not use them.
- Make the caller handle every documented outcome explicitly and fail closed on
  unknown or malformed signals.
- Update adjacent comments and documentation in the same change; remove stale
  explanations instead of preserving a comforting lie.
- Add or update tests for every matrix cell, invoking the production helper and
  its real caller seam. Do not replace the helper with a test-only
  reimplementation of the behavior under review.

## Review rubric

A reviewer must reconstruct the matrix from the diff, helper, call sites, and
tests. Verify that:

- every production branch has one documented semantic signal;
- all success outputs and failure-before-side-effect paths appear in the
  matrix and tests;
- the caller distinguishes semantic state from execution failure;
- no unrelated prerequisite blocks a branch that does not need it;
- unknown output fails safely rather than selecting a permissive branch;
- comments describe the behavior that the code actually performs; and
- evidence exercises the production helper, not a mock that can agree with an
  incorrect assumption.

An actionable review finding should name the helper and caller, identify the
missing or contradictory matrix cell, explain the resulting wrong branch or
side effect, and request the smallest contract, implementation, and test change
that closes the gap.

## Example

Suppose `resource_state` controls whether a caller reuses or creates a
resource. A sound contract returns exactly `present` or `absent` on success,
returns non-zero on lookup failure, and writes diagnostics only to standard
error. Its matrix includes at least:

| Input or precondition | Existing state | Requested action | Exact helper signal | Caller branch | Allowed side effect | Required evidence |
| --- | --- | --- | --- | --- | --- | --- |
| valid identifier | present | reuse | `present`, status `0` | reuse | no create | production helper and caller test |
| valid identifier | absent | reuse-or-create | `absent`, status `0` | create | one create | production helper and caller test |
| invalid identifier | unknown | any | no semantic token, non-zero status | stop | none | failure-before-side-effect test |
| dependency unavailable | unknown | any | no semantic token, non-zero status | stop | none | failure-before-side-effect test |

## Anti-patterns

- Returning a blank string for both "absent" and "lookup failed."
- Printing diagnostic prose to standard output and branching on a substring.
- Treating every zero exit as one semantic state when the helper has multiple
  successful outputs.
- Checking a creation-only prerequisite before a reuse branch.
- Updating a comment to describe the intended behavior while leaving the
  implementation or caller unchanged.
- Testing a copied conditional or mocked return value without executing the
  production helper.
- Adding one regression case while leaving another success token or an early
  failure path untested.

## Completion evidence

The change receipt must include the completed matrix, the exact helper and
consumer paths reviewed, and test identifiers or commands proving every cell.
For mutation-capable branches, evidence must also show that failure cells
produce no side effect and that success cells produce only the permitted side
effect. A passing aggregate test count without cell-to-test mapping is not
sufficient.
