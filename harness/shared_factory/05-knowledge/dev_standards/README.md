# DEV_STANDARDS (Composable Markdown Contract)

Created: 2026-07-18. The single "what we focus on when writing code" plane for
every mission: auto-dev (write side), auto-dev-finalize (reviewing our own
PRs), pr-review (reviewing others' PRs), and QA batteries.

## Loading Contract (every mission, every run)

1. Resolve the ordered folder list from the routed project's
   `project.yml dev_factory.dev_standards.paths` when present; the default
   is `[this folder, <domain>/05-knowledge/dev_standards,
   <project>/config/dev_standards]`. Projects may list 1-N folders. Entries
   resolve against the OS root first, then the project root. During the
   compatibility window, consumers may fall back to
   `dev_factory.quality_gates.paths` and the `quality-gates` path aliases.
2. In each folder, enumerate `*.md` excluding `README.md`; every file is an
   active gate focus. There is no registration step: dropping a new markdown
   into any listed folder extends the behavior of all missions on their next
   run. Later folders sharpen earlier ones; the strictest applicable rule
   wins.
3. Write-side consumers load standards BEFORE writing code. Review-side consumers
   (own PRs via auto-dev-finalize, others' PRs via pr-review) score findings
   against them and cite the gate filename in each finding (for example
   `SECURITY_ISOLATION.md`).
4. Validation-time checks live in the sibling `qa-gates/` plane
   (`dev_factory.qa_gates.paths`), consumed at acceptance/QA moments rather
   than diff time.

## File Shape

Each standards file states one focus and both sides of it:

```markdown
# <Focus Name>

Focus: <one sentence>.

## Write
- how implementation gets this right the first time

## Review
- how a reviewer scores it, and what is blocking

Blocking: <always | when ...>
```

## Extending (the whole point)

Add one markdown to change every mission. Example: create
`SECURITY_FOCUS.md` here (or a project-specific one in the project addendum
folder) describing how we focus on specific security aspects; the next run of
auto-dev, auto-dev-finalize, and pr-review picks it up automatically. Retire a
focus by deleting its file (leave a dated breadcrumb line in the WORKLOG of
the change that removed it).

## Blocking Classes

Findings in these classes block a run regardless of which file raised them:
correctness, security, tenant/data isolation, migration risk,
performance/leaks, missing or false tests, unmet acceptance criteria.
Style-level findings are fixed when trivial, otherwise logged with rationale.
A finding without a concrete failure scenario or maintainability cost is not
a finding.
