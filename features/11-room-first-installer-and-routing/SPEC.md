# Spec

Add room-first profile installation and validation.

## Commands

```bash
agentic-os init --target ~/agentic_os --profile profiles/example.yml
agentic-os profile create --target profiles/customer.yml
agentic-os profile validate profiles/customer.yml
agentic-os room create <room_slug> --root ~/agentic_os
agentic-os room update <room_slug> --root ~/agentic_os --from-profile profiles/customer.yml
```

## Acceptance

- Profile installs create only declared rooms.
- Room `CONTEXT.md` and `ROUTER.md` are generated from profile data.
- Claude/Codex pointer files still use `ROUTER.md`.
- Existing default init remains unchanged without `--profile`.
- Runtime validation supports profile-defined room roots.
