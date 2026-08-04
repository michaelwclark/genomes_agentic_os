# ControlPlaneStore Port (AGE-146)

## Decision

The control plane gains one provider-neutral `ControlPlaneStore` boundary.
The first slice covers the event ledger and named cursors only. Callers select
the store in one composition function with an explicit `control_plane` mapping:

```yaml
control_plane:
  backend: sqlite
  sqlite:
    path: harness/shared_factory/00-control-plane/state.db
    busy_timeout_ms: 5000
```

`build_control_plane_store()` returns the selected port; application callers do
not receive a datastore connection. The SQLite adapter owns connection setup and
delegates to the existing event/cursor state operations.

## Boundaries

- This change does not migrate or consolidate existing stores; AGE-85 owns that
  work.
- This change does not alter queue, lease, work-item, outbox, repair, or replay
  behavior; later vertical slices need their own contracts and conformance tests.
- PostgreSQL is intentionally unavailable. A real adapter requires a supported
  driver, dialect-specific migrations, and passed concurrency coverage for
  idempotency, claims, leases, fencing, and outbox recovery. Returning a fake
  adapter would falsely advertise shared-profile readiness.

## Verification

`tests/test_control_plane_store.py` runs the same event/cursor contract against
the SQLite adapter and statically verifies that the port module itself does not
import a concrete datastore driver.
