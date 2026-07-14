# Shared Factory Source

This is the source-owned seed for the installed OS's cross-domain shared
factory. The source tree intentionally contains only reusable, versioned
assets. Installation expands it into `harness/shared_factory/00-control-plane`
through `08-archive`, where live registries, knowledge, and run evidence belong.

| Folder | Purpose |
| --- | --- |
| [`00-programs/`](00-programs/) | Reusable OSProgram definitions shared across domains. |

Do not commit installed runtime queues, receipts, customer data, or generated
run logs here. Those are instance state, not package source.
