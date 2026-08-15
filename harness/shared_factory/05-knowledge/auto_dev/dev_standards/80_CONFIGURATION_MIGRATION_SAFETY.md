# Configuration and Rules Migration Safety

Executable configuration is production code. A migration that rewrites
persisted rules, templates, jq, feature flags, or tenant data is a blocking
correctness and compatibility change, even when application source is
unchanged.

Auto-Dev must fail closed unless it proves: the complete dependency closure;
exact runtime composed compilation before any write; preservation of tenant
customizations; idempotency, auditability, and tested recovery; and safety
while old and new pods overlap. Marker checks, row-count assertions, and
“reload the three named rows” are not proof of a safe migration.

Run `harness/bin/agentic-os-configuration-migration-gate` before self-review,
opposing review, readiness, or merge. The gate blocks matching configuration
migrations when these artifacts are absent.

When the migration or application change also changes the payload supplied to a
persisted rule or configuration consumer, apply
`85_RUNTIME_CONSUMER_CONTRACTS.md` as well. A successful composed compile does
not prove that the runtime consumer still receives the fields it expects.
