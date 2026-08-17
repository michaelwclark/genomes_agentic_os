---
name: auto-dev-qa
description: Run the project-configured risk-based QA gates as a standalone Auto-Dev step and record exact typed evidence without weakening unavailable-environment failures into passes.
---

# Auto-Dev QA

1. Read the ticket acceptance criteria, effective `qa_gates`, changed surface,
   current `autodev.json`, and its frozen context selection. For an LOS Rules
   Engine context marked `loaded`, QA must use the same bound concrete contract,
   dictionary, checks, snapshot freshness/coverage, redundancy status, and
   known findings that Readiness used—never a fresh ad hoc lookup.
2. Select the smallest complete static, unit, integration, end-to-end, manual,
   CI, and deployed checks justified by risk.
3. Run the checks through the project's canonical tooling. Keep raw logs out of
   chat; retain compact commands, identifiers, results, and artifact paths.
4. Classify failures as code, test, data, provider, or environment failures.
   Use CI fallback only when project policy permits it and record why.
5. Map every acceptance criterion to evidence or a gap. Record `qa` as
   completed only after evidence is current for the exact revision.

For Rules Engine work, `kit-unavailable`, stale, or incomplete snapshots require
an explicit unknown/insufficient-evidence result. Report only high-confidence
problems; do not turn healthy cases, unused-rule hypotheses, or raw tenant
values into QA noise.

## LOS Django child delivery

For `Lenders-Cooperative/los-app-los-django`, create a Jira QA Automation
Assessment subtask under the root Jira when the application PR is opened. The
subtask is always created; Playwright implementation is contextual.

- If automation adds no meaningful coverage or is genuinely infeasible, close
  the assessment with a typed policy decision and concrete reason.
- If automation is required, treat the subtask as a child Auto-Dev delivery in
  `Lenders-Cooperative/los-qa-automation`. Use a feature branch and PR; do not
  push the delivery directly to `main`.
- Analyze the application diff, acceptance criteria, existing Jira tests, and
  `.agents/skills/qa-analysis/SKILL.md` in the Django repository before naming
  files. The plan normally includes
  `tests/jira/<PARENT>/<feature>.spec.ts`,
  `tests/jira/<PARENT>/README.md`, any reusable `pages/**`, `helpers/**`, or
  fixture changes, required tags/environment, evidence, and the exact
  validation command.
- Bind the child Jira, repository, PR, revision, checks, and outcome back to the
  parent work item. The parent QA gate is terminal only when the child reaches
  the project-configured completion boundary or the typed skip is accepted.
