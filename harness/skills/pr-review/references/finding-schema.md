# Finding Schema

Every specialist reviewer returns only actionable findings at or above the requested threshold.

```yaml
agent: <agent-name>
severity: CRITICAL | HIGH | MEDIUM | LOW
confidence: confirmed | likely | open-question
category: security | bug | architecture | bad-pattern | abstraction | missing-test | missing-docs | acceptance | database | devops | readability | frontend | django
file: path/to/file.ext
line: L42 or null
method_or_symbol: method_name or null
jira_criterion: AC-1 or null
memory_refs:
  - source: Unified Memory MCP | MEMORY.md | none
    verified_current: true | false
why_it_matters: one or two concrete sentences
reproduction_or_trace: exact call path, failing scenario, or missing verification path
pattern_reference: path/to/existing-good-pattern.ext or null
comment_depth: Quick | Standard | Deep
suggested_code: |
  concrete patch sketch or null
copy_paste_comment_markdown: |
  <question-led GitHub markdown in natural, varied phrasing — no stock opener>
```

The Graybeard Orchestrator rejects findings that lack:

- A concrete file, method, or Jira acceptance anchor.
- A specific production, security, acceptance, data, test, documentation, or architecture risk.
- Evidence from current code, Jira, CI, tests, PR diff, or verified memory.
- A copy/paste-ready GitHub markdown comment.
