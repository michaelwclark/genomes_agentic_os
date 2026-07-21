# Host Auto-Doctor

Host Auto-Doctor is the policy-composed health and bounded-recovery runtime for
Agentic OS hosts. Shared workflow policy and host overlays are Markdown files
with YAML front matter under the installed `host_agentic_os_health` program.

## Run a report

```bash
agentic-os host health-report --root /path/to/agentic_os --host bigmac
agentic-os host health-report --root /path/to/agentic_os --host genomesbox
```

Add `--apply-safe-repairs` to execute only allowlisted, reconstructable actions.
Add `--apply-notion` to replace the host's configured page after verifying the
workspace is exactly `Genome's Notion`. The page id is read from the host's
identity policy; `--notion-page-id` is an explicit override.

Each run writes immutable JSON and Markdown receipts plus `latest.json` and
`latest.md`. A report contains the host status, observed metrics, findings,
repair receipts, verification after any repair, policy sources, last-run time,
and next-run time.

The command returns zero when collection and publication succeed even if the
host report is degraded; use `--fail-on-unhealthy` when a CI or interactive
caller intentionally wants health status reflected in the process exit code.

## Policy composition

Policies use `api_version: auto-doctor-policy/v1`. The engine loads shared
workflow files first, followed by the selected host directory. When two layers
emit the same finding code, the later host layer wins. Markdown can select only
built-in probes and repair actions; it cannot inject arbitrary shell commands.

Supported probes cover thresholds, process patterns, systemd user services,
launchd services, HTTP endpoints, Docker container health, Linux PSI, macOS
memory/swap, disk, load, and process inventory.

The automatic repair allowlist is deliberately narrow:

- restart or start an owned systemd user service;
- restart an exactly named reconstructable Docker container.

Reboots, root services, file deletion, indexing changes, unknown process kills,
and repeated unsuccessful repair attempts remain operator actions.

## Scheduling

The canonical cadence is 06:00, 14:00, and 22:00 America/Chicago. Install the
provided systemd user timer on Linux or launchd plist on macOS. The installed
unit runs a report, applies safe repairs, verifies the result, updates the
durable receipt, and projects the latest state to Notion.
