# State Plane

This package implements the indexed SQLite state plane used by the local
runtime. Events, queues, and cursors project durable operating artifacts.
`work_items` is authoritative for current lifecycle and attention state; packet
files and external trackers are evidence and content surfaces.

| File | Responsibility |
| --- | --- |
| `db.py` | Database connection, schema, migrations, and WAL configuration. |
| `events.py` | Append and query normalized events. |
| `queue.py` | Runtime queue projection and transitions. |
| `cursors.py` | Connector and importer cursor tracking. |
| `importers.py` | Import existing file-backed state into SQLite. |
| `work_items.py` | Canonical work state, transition history, legacy import, and active context. |
| `cli.py` | State-plane diagnostic and maintenance commands. |
| `control_plane.py` | Provider-neutral event/cursor port and explicit backend composition seam. |
| `adapters/sqlite.py` | SQLite implementation of the first control-plane contract slice. |

See [`../../../docs/design-notes/state-plane.md`](../../../docs/design-notes/state-plane.md)
for the schema and migration contract.
See [`../../../docs/design-notes/control-plane-store-port.md`](../../../docs/design-notes/control-plane-store-port.md)
for the AGE-146 boundary and its intentionally deferred PostgreSQL profile.
