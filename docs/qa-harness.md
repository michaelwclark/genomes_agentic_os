# QA Harness

The QA harness proves that Agentic OS can be installed, upgraded, and operated
without silently losing the things an existing user relies on. It is not a
replacement for focused unit tests; it is the evidence layer for real install
and upgrade paths.

## What it proves

- A fresh install creates a usable, correctly shaped OS.
- An upgrade preserves user-owned work, objects, and local customizations.
- Expected changes are distinguishable from protected-content loss.
- A verdict identifies the evidence, command, and failure boundary rather than
  only reporting a red or green result.

## Run the right check

Use the source harness instructions for exact commands and fixtures:

- [Harness quick start](https://github.com/michaelwclark/genomes_agentic_qa/blob/main/README.md)
- [Operations and failure handling](https://github.com/michaelwclark/genomes_agentic_qa/blob/main/docs/operations.md)

The usual sequence is: run the focused source tests, run a fresh-install check,
run the seeded upgrade check where the changed surface can affect existing
users, then compare the previous and new paths. Keep the exact version and
artifact identity with each result.

## Reading a verdict

A useful verdict names the scenario, tested revision, fixture, command,
expected invariants, and the evidence artifact. When it fails, classify the
failure before retrying: code defect, fixture issue, host/runtime problem, or
provider/environment prerequisite. Preserve the receipt and create a follow-up
work item for a real gap; do not hide a failed scenario behind a broad passing
suite.

## Safety boundary

Harness runs use disposable or explicitly identified test roots. They must not
modify a live installed OS, reuse production credentials, or treat a copied
runtime artifact as proof that the source package works. The source repository
remains the canonical, executable reference; this page makes that capability
discoverable from the main handbook.
