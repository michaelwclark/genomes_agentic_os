# Investigation

Reviewed current official Codex configuration docs and local installed CLI
behavior.

Sources used:

- `https://developers.openai.com/codex/config-basic`
- `https://developers.openai.com/codex/config-reference`
- `https://developers.openai.com/codex/config-sample`
- `https://developers.openai.com/codex/guides/agents-md`
- `https://developers.openai.com/codex/mcp`
- `https://developers.openai.com/codex/hooks`
- `https://developers.openai.com/codex/config-schema.json`

Local runtime evidence:

- `codex --version`: `codex-cli 0.131.0-alpha.9`
- `codex --help`: confirmed `--profile`, `--config`, `--sandbox`,
  `--ask-for-approval`, `--search`, `--cd`, and `--add-dir`.
- `codex debug --help`: confirmed debug tools for models, app-server, and
  prompt-input.
