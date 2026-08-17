# Configuration Composition Gate

Block readiness for executable-configuration migrations without full dependency
closure, exact runtime composed-compile evidence before and after writes,
undefined-helper coverage, tenant-customization preservation/readback,
idempotency and recovery proof, and old/new pod rolling compatibility evidence.

Green tests that only assert row counts or marker strings do not satisfy this
gate. Review the exact commit and migration head; a later fix does not make the
unsafe head releasable.
