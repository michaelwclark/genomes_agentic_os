# Project Domain Investigate

Invoke as `/project-domain-investigate <topic-or-ticket>`.

1. Load the `project_domain_intelligence` program context pack and the target
   project instance.
2. Select the smallest relevant evidence-backed domain articles from tracker
   text, paths, symbols, and explicit focus.
3. Emit a context receipt with selected and skipped article IDs, revisions,
   budget, and uncovered questions.
4. Return source precedence and the receipt ID. If unavailable, return an
   explicit `no_context` receipt; do not invent guidance.

This command is read-only. Use an approved project workflow for article writes.
