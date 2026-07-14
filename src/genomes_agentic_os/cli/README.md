# Command-Line Package

This package defines the `agentic-os` and `aos` command-line interface. Each
feature area owns a small registration module; `__init__.py` composes those
modules into the top-level parser and dispatches to operation code in the
parent `genomes_agentic_os` package.

| Module group | Commands covered |
| --- | --- |
| `scaffold.py`, `project.py`, `customer.py` | Install roots and create or operate domains, projects, and customer OS instances. |
| `spec.py`, `plans.py`, `docs.py` | Capture and move Specs through their lifecycle and operate documentation. |
| `workflow.py`, `automation.py`, `run_lifecycle.py` | Inspect, validate, and execute workflows, automations, and runs. |
| `runtime.py`, `state.py`, `event_graph.py` | Operate queues, schedules, state projections, and event chains. |
| `routing.py`, `capability.py`, `adaptive.py` | Resolve context, inspect capabilities, and evaluate model routing. |
| `source_watch.py`, `resource_graph.py`, `notion.py` | Query or synchronize connected information sources. |
| `cockpit.py`, `operator.py`, `hosts.py` | Render operator surfaces and inspect local or remote hosts. |
| `doctor.py`, `validate.py`, `config.py`, `self_improvement.py` | Diagnose, configure, validate, and improve an installation. |

Keep argument parsing and presentation here. Business logic belongs in focused
modules one level up so it can be reused by tests, workflows, and future GUI
adapters without invoking the CLI.
