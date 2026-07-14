# State Plane

This package implements the indexed SQLite projection used by the local runtime.
It supplements durable file artifacts with fast queries while keeping files and
receipts as the inspectable operating record.

| File | Responsibility |
| --- | --- |
| `db.py` | Database connection, schema, migrations, and WAL configuration. |
| `events.py` | Append and query normalized events. |
| `queue.py` | Runtime queue projection and transitions. |
| `cursors.py` | Connector and importer cursor tracking. |
| `importers.py` | Import existing file-backed state into SQLite. |
| `cli.py` | State-plane diagnostic and maintenance commands. |

See [`../../../docs/design-notes/state-plane.md`](../../../docs/design-notes/state-plane.md)
for the schema and migration contract.
