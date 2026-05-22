# Memory

Automation maturity holdout validation should test both a passing safe path and
a failing unsafe path. The useful command sequence is:

```bash
uv run agentic-os init --target "$ROOT"
uv run agentic-os project create support support_intake --root "$ROOT" --repo /tmp/support-intake --notion https://www.notion.so/support --jira SUPPORT --lane ready
uv run agentic-os automation create support support thread_intake --root "$ROOT"
uv run agentic-os automation check support support thread_intake --root "$ROOT"
uv run agentic-os automation set-maturity support support thread_intake propose --root "$ROOT"
uv run agentic-os automation set-maturity support support thread_intake prepare --root "$ROOT"
uv run agentic-os automation attach support support thread_intake --project support_intake --root "$ROOT"
uv run agentic-os validate --root "$ROOT"
```

`propose` should exit non-zero while evidence blockers remain; `prepare` should
succeed.
