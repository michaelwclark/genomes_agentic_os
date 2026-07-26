# QA Gates (Composable Markdown Contract)

Created: 2026-07-19. The validation-time counterpart to the quality-gates
plane. Quality gates score DIFFS while writing and reviewing code; QA gates
script VALIDATION: how acceptance is proven, what always gets regression
attention, which environments and tenants must be exercised, and what
evidence gets captured.

## Consumers And Moments

- auto-dev-finalize Phase 5: `ac_satisfied` verification and the acceptance
  lane of the review battery.
- pr-review (others' PRs): acceptance/report mode checks.
- qa-analysis and ticket QA runs: test planning and evidence capture.
- post_merge_jira_routing: the manual-regression classification.
- Human QA handoff: the packet's HOLDOUT_QA.md / HOLDOUT_QA_RESULTS.md and
  QA_HANDOFF artifacts are where these gates' outputs land.

## Loading Contract

1. Resolve the ordered folder list from the routed project's
   `project.yml dev_factory.qa_gates.paths` when present; default is
   `[harness/shared_factory/05-knowledge/qa-gates, <project>/config/qa-gates]`.
   Entries resolve against the OS root first, then the project root.
2. In each folder, every `*.md` except `README.md` is an active QA gate.
   Later folders sharpen earlier ones; the strictest applicable rule wins.
3. No registration: dropping a markdown into any listed folder extends the
   next run of every consumer.

## File Shape

```markdown
# <Focus Name>

Focus: <one sentence>.

## Verify
- what must be proven, and how

## Evidence
- what artifacts capture the proof, and where they land

Blocking: <always | when ...>
```
