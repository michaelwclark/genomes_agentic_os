# `genomes_agentic_os` Package

This package implements the `agentic-os` and `aos` command-line tools. It is a
layered, file-first Python application: CLI adapters call focused operation
modules, which receive the OS root explicitly and read or write durable files.

| Area | Important modules | Responsibility |
| --- | --- | --- |
| CLI composition | [`cli/`](cli/) | Argparse command groups, handlers, and shared CLI rendering. |
| Scaffolding | `scaffold.py`, `room_profile.py`, `work_lifecycle.py`, `lifecycle.py` | Create and repair installed roots, domains, projects, rooms, and work packets. |
| Routing and context | `routing.py`, `capability_registry.py` | Resolve work to the narrowest room and expose its capabilities. |
| Specs and resources | `spec_engine.py`, `resource_graph.py`, `doc_config.py` | Canonical Spec lifecycle, bounded resource queries, and document placement. |
| Runtime and state | `runtime_ops.py`, `supervisor.py`, `state/`, `event_graph.py` | Queues, schedules, heartbeats, SQLite projection, events, and guarded dispatch. |
| Automations and workflows | `automation_ops.py`, `automation_control.py`, `workflow_ops.py` | Maturity gates, readiness, execution contracts, and receipts. |
| Connected sources | `source_providers.py`, `source_watch.py`, `source_observation.py` | Normalize and poll external/provider data without leaking provider shapes. |
| Activity analytics | `activity_ingestion.py` | Convert opted-in Slack, GitHub, Jira, Linear, and Agentic OS activity into metadata-only metric events. |
| Operator surfaces | `cockpit.py`, `cockpit_render.py`, `conversation_logging.py`, `conversation_reports.py` | Cockpit, conversation indexing, transcripts, and GUI-facing operations. |
| Adaptive routing | `adaptive_*.py` | Offline model/tier assessment, policy, evaluation, and redacted receipts. |
| Installation and maintenance | `config_ops.py`, `update_ops.py`, `migrations.py`, `doctor.py`, `validate.py` | Configuration, updates, migration, health checks, and structural validation. |
| Customer factory | `customer.py` | Render isolated customer OS installations from verified profiles. |

Dependency direction is toward focused operations and explicit filesystem
primitives. Do not make operation modules import CLI handlers, introduce hidden
global root state, or move copyable harness/templates into this import package.
