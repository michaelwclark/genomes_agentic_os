# Auto-Dev Context Pack

Load only:

1. this program's `program.md`, `components.yml`, `RULES.md`, and `TOOLS.md`;
2. the selected workflow's `workflow.md` and `workflow.yml`;
3. routed domain/project context and project `config/development.yml`;
4. effective Markdown policy sources reported by the resolver;
5. the active run request/state/receipts and exact source-of-truth evidence.

Defer unrelated workflows, domains, raw logs, archived runs, and provider
payloads until a named gate needs them.
