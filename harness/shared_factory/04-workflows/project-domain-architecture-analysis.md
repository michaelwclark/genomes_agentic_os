# Workflow: Project Domain Architecture Analysis

## Purpose

Produce topic-focused, evidence-backed project-domain guidance without treating
folder structure as the domain model. This is the canonical compatibility
workflow owned by `project_domain_intelligence`.

## Inputs

- Project root and `.project-domain-analysis/config.yml`.
- Focus topic, tracker text, changed paths, or explicit symbols.
- Existing domain registry, articles, evidence, and receipts.

## Steps

1. Inventory source, tests, configuration, and runtime evidence.
2. Choose the smallest useful domain/topic boundary.
3. Use the `project-domain-analysis` toolkit to create or refresh evidence.
4. Record commands, important symbols, data structures, extension seams, tests,
   failure modes, and conflicting evidence when present.
5. Emit a context receipt for every grooming, auto-dev, planning, review, or
   documentation-upkeep consumer.

## Guardrails

- Source evidence wins over generated articles.
- Mark claims without evidence as hypotheses.
- Never copy large source blocks, secrets, or customer data into an article.
- Scheduled runs are observe-only and write a deterministic receipt only.
