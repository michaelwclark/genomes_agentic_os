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
workspace matches `notion_workspace` in the host policy or the explicit
`--verified-workspace` value. The page id and optional `notion_token_env` are
also read from policy; `--notion-page-id` and `--token-env` are explicit
overrides. A missing expected workspace fails closed before the Notion write.

Optional report distribution remains provider-neutral:

- `--apply-http-report` sends the report to `report_ingest_url` using the
  bearer token named by `report_token_env` (or `--http-token-env`);
- `--apply-report-drop` copies `latest.json` to the fixed SSH target declared
  by `report_drop_target`.

When upgrading an existing installation, migrate the policy keys, token
environment names, and timer/service flags together with the package so a
scheduled run never mixes old configuration with the new CLI contract.

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

## Host sentinel (off-box, 5-minute)

Auto-Doctor's 3x/day cadence runs *on* the host it inspects, so a host that is
fully down or unreachable cannot report on itself. genomesbox went down
uncleanly twice in 24 hours (2026-09-21 and 2026-09-22, ~4h45m each) and
nobody was alerted; after it rebooted, failed systemd units stayed broken for
~19h before anyone noticed. `agentic-os-host-sentinel` closes that gap: it
runs off-box (on bigmac, watching genomesbox) every 5 minutes under launchd,
independent of the Agentic OS runtime and queue, so it keeps working even
when the thing it watches does not. It is stdlib-only Python and makes
exactly one `ssh` subprocess per run — no other network calls.

Each run alerts through `agentic-os-notify` (source `runtime.host_sentinel`)
on:

- **unreachable** — two consecutive failed/timed-out SSH probes (`critical`),
  and **reachable again** (`info`) once it comes back;
- **reboot** — the remote `boot_id` changed since the last successful probe;
  `critical` if the previous boot's journal does not end with a shutdown
  marker (unclean/crash), `warning` if it does (clean/intentional);
- **persistent problems** — a failed systemd unit (system or user) or an
  unhealthy/restarting Docker container that is still present after two
  consecutive probes (`warning`), and **recovered** (`info`) once it clears.

### Install

```bash
# render the template
PYTHON=$(command -v python3)
OS_ROOT="$HOME/agentic_os"
HOST=genomesbox
sed -e "s#{{OS_ROOT}}#${OS_ROOT}#g" -e "s#{{HOST}}#${HOST}#g" -e "s#{{PYTHON}}#${PYTHON}#g" \
  "${OS_ROOT}/templates/runtime/host-sentinel.launchd.plist.template" \
  > "$HOME/Library/LaunchAgents/com.genome.agentic-os.host-sentinel.${HOST}.plist"

# load it
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.genome.agentic-os.host-sentinel.${HOST}.plist"
```

A manual run (safe to run any time, including a dry preview):

```bash
agentic-os-host-sentinel --root "$OS_ROOT" --host genomesbox --dry-run
```

### State and receipts

Under `harness/shared_factory/06-runs-and-logs/host-sentinel/`:

- `<host>.state.json` — consecutive-unreachable count, last known boot id,
  per-problem alert streaks; read/written atomically each run.
- `<host>.latest.json` — the most recent probe result and any notifications
  sent, for readback without re-probing.
- `<host>.launchd.out.log` / `<host>.launchd.err.log` — launchd stdout/stderr.

The sentinel complements the 3x/day Host Auto-Doctor report rather than
replacing it: Auto-Doctor diagnoses and safely repairs a *reachable* host in
depth on a slow cadence; the sentinel only watches for "is it up, and did it
come back clean" on a fast cadence, and keeps doing that when Auto-Doctor's
own host cannot run.
