# Spec Adapters

These adapters connect the canonical Spec lifecycle to the tracking system a
domain or project selects. The Spec Engine owns statuses and validation; an
adapter only translates that contract to a provider.

| File | Provider | Responsibility |
| --- | --- | --- |
| `base.py` | Shared | Adapter and transport contracts. |
| `filesystem.py` | Filesystem | Durable local work-item packets under a project's `work-items/` tree. |
| `linear.py` | Linear | Linear issue creation and lifecycle synchronization. |
| `jira.py` | Jira | Jira issue creation and lifecycle synchronization. |

Provider-specific fields should remain behind this boundary so project routing
and UI code can work with one stable Spec model.
