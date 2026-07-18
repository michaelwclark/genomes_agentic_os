# Execution Fabric Router

| Request | Route |
| --- | --- |
| Program configuration or activation planning | This program |
| Legacy file-backed queue operation | `runtime-operator` |
| Worker implementation or queue backend code | Owning source project |
| Mutable tasks, attempts, leases, or heartbeats | Installed runtime state |

Do not store mutable queue or worker state in this source-owned definition.
