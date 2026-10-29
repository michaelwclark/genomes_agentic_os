# Off-box disk monitoring

The scheduled host sentinel reads the remote Linux root filesystem with `df -Pk /` and `df -Pi /` on each existing five-minute SSH probe. It requires no root access or agent on the watched host. The interactive `agentic-os-monitor` is not a replacement for this scheduled check.

The sentinel warns at 85% disk or inode usage, or 20 GiB available. It sends a critical alert at 95% usage or 5 GiB available. Consecutive samples 1–30 minutes apart also warn for consumption of at least 2 GiB/minute, or projected exhaustion within six hours when usage is at least 70%. Projected exhaustion within one hour is critical. Forecasts describe the observed rate, not a guarantee.

Early growth warnings are independent of those fullness limits. The state retains seven days of five-minute samples (at most 2,017). Receipts include recent, six-hour and daily growth, an exponentially weighted normal baseline with a 24-hour half-life, acceleration, projected exhaustion, sample age and warm-up status. Capacity changes reset incompatible history. Large cleanup drops start a fresh recent segment while retaining older samples for audit.

The recent regression needs at least 30 minutes of observations. A growth candidate must remain abnormal for another 30 minutes, and the latest 15-minute rate must still be positive enough to show that consumption continues. Alert signals are:

- At least 2 capacity percentage points/day, with a 4 GiB/day floor.
- At least three times the normal baseline, and above it by at least 0.5 capacity points/day or 2 GiB/day, once six hours of normal baseline observations exist.
- A doubling of the latest half-hour rate relative to the preceding half hour, with the same absolute deviation floor.
- Projected exhaustion within 14 days. Once sustained, a projection below 24 hours is critical.

The baseline freezes during candidate or active anomalies so growing log files do not become the new normal. Gaps longer than 15 minutes reset the persistence clock; a previous incident is not declared recovered merely because trend data is warming up. A brief stopped burst should not become a sustained-growth incident.

Acceptance example: starting at 12% utilization and growing eight capacity percentage points/day raises an alert at 60 minutes, around 12.33% utilization. This is tested with simulated observations. The user's recollection of historical utilization is not inserted as measured data; live baseline learning starts from actual samples.

Missing or invalid disk telemetry for two probes produces a warning and cannot clear a previously critical incident. Pressure alerts fire immediately, escalate on the next sample, repeat after 30 minutes while unresolved, and report recovery. Failed disk-notification commands retry on the next cycle. The alert policy still governs quiet hours and delivery; critical alerts bypass quiet hours. Local desktop delivery receipts do not prove the user saw the notification.

Probe and alert state live in `harness/shared_factory/06-runs-and-logs/host-sentinel/<host>.latest.json` and `<host>.state.json`. Existing state is backward compatible. Launchd output/error logs retain one archive and rotate after 1 MiB between cycles. This bounds normal periodic output; it is not protection against an individual hung process producing unlimited output.

On a disk alert, the scheduled CLI automatically starts a bounded read-only investigation, at most once per hour. It captures filesystem, journal, directory, deleted-open-file, process-name and container-retention metadata. It does not read log contents, process arguments, environment variables or database records. Individual remote scans are time bounded; partial output is labeled. Diagnostic receipts are owner-readable, limited to 64 KiB of output each, and retain the latest 12 files under the sentinel state directory's `diagnostics/` folder. A failed diagnostic does not prevent the alert or normal state receipt.

The monitor never deletes host data or stops services. The incident's cleanup stage requires an identified producer and verified retention policy; it is explicitly marked pending in the diagnostic receipt until configured. Preserve databases and dirty worktrees. Confirm the producer's rotation policy, reclaim only identified disposable material, then verify available bytes and core service health. Docker daemon log defaults apply to newly created containers; verify each existing container's effective logging configuration separately.

This off-box monitor can detect loss of the watched host, but it cannot run while the monitoring Mac is asleep or disconnected. Host-local limits, a local systemd timer, and a second independent always-on observer must be verified before claiming continuous coverage.
