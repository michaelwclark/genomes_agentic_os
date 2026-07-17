# Project Domain Architecture Analysis

## What this does

Builds or refreshes a bounded, evidence-backed article about one project topic
and emits the context receipt consumed by grooming, implementation, review, or
documentation upkeep. Source code and tests remain authoritative; articles are
searchable orientation material, never a replacement for live evidence.

## Inputs

- Project root and `.project-domain-analysis/config.yml`.
- Focus topic, tracker text, changed paths, or explicit symbols.
- Existing domain articles, evidence, receipts, and source revision.
- Optional consumer name and context budget for receipt generation.

## Outputs

- One created, refreshed, or unchanged topic article.
- Evidence references for commands, symbols, structures, patterns, tests,
  failures, and extension seams.
- A deterministic `project-domain-context/v1` receipt listing selected and
  skipped articles, source revision, query, and uncovered questions.
- Drift or validation receipt when the requested operation does not write an
  article.

## States

`discovered -> bounded -> evidence_collected -> article_proposed -> validated -> available`.
Any non-terminal state may become `blocked`, `stale`, `invalid`, or `cancelled`
with a receipt. `retired` is terminal and preserves history.

## Steps

1. Resolve the project configuration and current source revision.
2. Bound the smallest topic that answers the consumer's question.
3. Inventory relevant source, tests, configuration, commands, and safe runtime
   evidence; record conflicting evidence instead of averaging it away.
4. Create or refresh the article with commands, important symbols, data
   structures, good patterns, risky or failed patterns, tests, and extension
   guidance.
5. Validate required sections, evidence paths, source precedence, and article
   identity. Preserve the previous article as a content-addressed backup before
   replacement.
6. Retrieve the smallest matching article set and emit a context receipt for
   the named consumer. Record uncovered questions explicitly.

## Validations

- Configuration paths stay inside the project root.
- Article IDs are stable lowercase slugs and cannot traverse directories.
- Required evidence, patterns, risks/failures, and extension sections exist.
- Source revision and selected article paths are recorded deterministically.
- Scheduled execution is observe-only and cannot write articles.
- Secrets, customer data, large source excerpts, and unsupported claims are
  absent from articles and receipts.

## Success modes

- `available`: a valid article and context receipt are ready for consumption.
- `unchanged`: current evidence does not require a new article revision.
- `no_context`: no article matches; the receipt names uncovered questions and
  the caller continues with bounded source inspection.
- `retired`: obsolete guidance is removed from retrieval while its backups and
  receipts remain available for audit.

## Failure modes and recovery

- Missing or malformed config: `blocked`; repair config and rerun validation.
- Invalid article identity or escaping path: `invalid`; reject without writes.
- Contradictory or stale evidence: `stale`; route to operator attention and
  collect fresh source evidence before replacement.
- Partial write or invalid refreshed article: restore the content-addressed
  backup with `domain-analysis rollback <article-id>` and revalidate.
- No matching article: emit `no_context`; never invent domain guidance.
- Scheduled refresh error: emit an attention receipt and require manual retry;
  article writes remain disabled.

## Events and receipts

Emit `domain.discovered`, `domain.evidence_collected`, `domain.article_proposed`,
`domain.article_validated`, `domain.context_loaded`, `domain.stale`, and
`domain.retired`. Store article backups and drift/context receipts under the
configured runs directory; do not store raw source dumps.

## Cleanup and handoff

Handoff the context receipt ID, selected article paths, source revision, and
uncovered questions. Retention may consolidate old drift receipts, but must keep
the latest successful receipt and every backup still referenced by rollback.

