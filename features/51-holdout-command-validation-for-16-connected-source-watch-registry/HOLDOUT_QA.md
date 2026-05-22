# Holdout QA

Run a fresh temp-root command matrix:

```bash
uv run agentic-os init --target <temp-root>
rm <temp-root>/shared_factory/05-knowledge/commands/os-watch-source.md
rm <temp-root>/shared_factory/05-knowledge/templates/runtime/watch-source.yml
uv run agentic-os docs update --root <temp-root>
uv run agentic-os validate --root <temp-root>
uv run agentic-os connected-system list --root <temp-root>
uv run agentic-os connected-system doctor notion_genome --root <temp-root>
uv run agentic-os watch-source create agentic_os_kanban --root <temp-root> --external-ref database_id=366683b48dab81a1ab5fc73e7e1f5c60 --enabled
uv run agentic-os watch-source list --root <temp-root>
uv run agentic-os watch-source doctor agentic_os_kanban --root <temp-root>
uv run agentic-os watch-source poll agentic_os_kanban --root <temp-root> --dry-run
uv run agentic-os watch-source run-due --root <temp-root> --dry-run
uv run agentic-os watch-source poll agentic_os_kanban --root <temp-root> --apply
```

Then corrupt the watch-source cursor and dedupe entries and confirm doctor
fails closed.

Run full tests:

```bash
uv run --extra dev pytest -q
```
