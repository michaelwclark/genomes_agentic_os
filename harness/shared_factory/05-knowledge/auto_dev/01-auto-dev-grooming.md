# Auto-Dev: grooming

Use `/auto-dev-grooming` to turn rough intent into implementation-ready tracker
truth. Grooming can be run for an epic, story, task, bug, subtask, spike, or the
project's equivalent work-item type.

## Inputs

- the live tracker item or captured idea;
- relevant comments, linked incidents, designs, support context, and prior work;
- the routed domain and project vocabulary;
- artifact contracts for the target tracker and item type;
- existing repository/configuration/environment evidence when it changes scope.

Tracker readback outranks an old local copy. Existing useful detail should be
preserved and improved, not replaced with a generic template.

## Actions

1. Explain the user or business problem and the desired outcome in plain
   English.
2. Separate observed facts, assumptions, hypotheses, product choices, and open
   questions.
3. Define in-scope and out-of-scope behavior and the smallest valuable slice.
4. Write observable acceptance scenarios, including important negative and
   failure paths.
5. Identify affected systems, repositories, data, integrations, tenants,
   environments, security boundaries, and migration concerns at the level the
   evidence supports.
6. Record dependencies, rollout/compatibility risks, QA needs, documentation,
   monitoring, and release implications.
7. Decompose large work into coherent child items with clear ownership and
   ordering when one item is not safely buildable.
8. Route uncertain causation to Detective instead of asserting a root cause.
9. Render tracker changes through Create Artifacts, obtain any required write
   approval, and verify the final provider content by readback.

Use bounded subagents when repository mapping, historical evidence, or domain
research can proceed independently. The coordinator reconciles conflicting
findings before updating the tracker.

## Required evidence

The packet records source links/identifiers, important evidence, decisions,
open questions, artifact contract fingerprint, any approval, and provider
readback. The work log states what changed in the scope and why.

## Done criteria

Grooming is complete when a developer unfamiliar with the conversation can
understand the problem, scope, acceptance behavior, risks, dependencies, and
verification expectations without guessing. The live tracker is the resulting
source of truth and its readback matches the intended update.

If one product, security, ownership, or data question materially changes the
solution, stop with that single explicit blocker and the evidence already
gathered. Grooming does not write code, select an unsupported implementation,
or invent missing product decisions.
