# Execution Fabric CRUD Boundaries

- Create: source-package install adds the inactive program definition.
- Read: program discovery and configuration readback are always safe.
- Update: guarded configuration changes may select a mode after readiness checks.
- Delete: removal is not a runtime control; disable or return to filesystem mode.

Mutable tasks and workers are runtime resources and are not CRUD-managed here.
