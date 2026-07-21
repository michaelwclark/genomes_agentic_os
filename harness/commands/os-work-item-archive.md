# Work Item Archive Health

Use this command to inspect or run the retention archive:

```bash
agentic-os work-item-archive --root ~/agentic_os --dry-run
agentic-os work-item-archive --root ~/agentic_os --apply
```

The command reads each project's lifecycle policy, moves only retained terminal
packets to `work-items/99-archived/`, preserves `REOPEN.md` packets, migrates
canonical state-plane paths, and writes a receipt. It never deletes a packet.
