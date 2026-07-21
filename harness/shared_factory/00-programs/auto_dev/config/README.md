# Auto-Dev configuration

The executable, composable Auto-Dev policy is the Markdown plane at
`harness/shared_factory/05-knowledge/auto_dev/`. Domain additions live in
`domains/<domain>/05-knowledge/auto_dev/`; project additions live in
`domains/<domain>/02-projects/<project>/config/auto_dev/`.

The engine reads those folders in root, domain, project, invocation order and
records every source plus a fingerprint. A project adds only what is genuinely
different; it never copies the root stage files.

Host, VPN, cloud, and upper-environment rules use the parallel
`environment_access` plane. Credentials never belong in either plane.

`examples/` contains copyable machine-readable project overlays when a runtime
needs a provider-specific safety adapter. They are examples, not automatic
installed-project mutations. Replace explicit sentinel values, merge only the
documented section into the owning project's live config, validate, and start a
new Development Delivery run so the exact commands are frozen into task state.

The LOS Django example uses the source-owned
`agentic-os-los-fast-worktree-health.py` wrapper. Replace
`__AGENTIC_OS_ROOT__` with the absolute installed OS root before copying its
`runtime:` mapping. The wrapper fails closed when shared Postgres, Redis, or
Valkey is unavailable because database/cache absence cannot then be proved.
