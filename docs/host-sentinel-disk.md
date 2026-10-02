# Off-box disk monitoring

The scheduled host sentinel reads the remote Linux root filesystem with `df -Pk /` and `df -Pi /` on each existing five-minute SSH probe. It requires no root access or agent on the watched host. The interactive `agentic-os-monitor` is not a replacement for this scheduled check.

The sentinel warns at 85% disk or inode usage, or 20 GiB available. It sends a critical alert at 95% usage or 5 GiB available. Consecutive samples 1–30 minutes apart also warn for consumption of at least 2 GiB/minute, or projected exhaustion within six hours when usage is at least 70%. Projected exhaustion within one hour is critical. Forecasts describe the observed rate, not a guarantee.

Missing or invalid disk telemetry for two probes produces a warning and cannot clear a previously critical incident. Pressure alerts fire immediately, escalate on the next sample, repeat after 30 minutes while unresolved, and report recovery. Failed disk-notification commands retry on the next cycle. The alert policy still governs quiet hours and delivery; critical alerts bypass quiet hours. Local desktop delivery receipts do not prove the user saw the notification.

Probe and alert state live in `harness/shared_factory/06-runs-and-logs/host-sentinel/<host>.latest.json` and `<host>.state.json`. Existing state is backward compatible. Launchd output/error logs retain one archive and rotate after 1 MiB between cycles. This bounds normal periodic output; it is not protection against an individual hung process producing unlimited output.

The monitor never deletes data or stops services. On a disk alert, establish the largest directories, individual file sizes, growth rate, writing process, and deleted-but-open files before cleanup. Preserve databases and dirty worktrees. Confirm the producer's rotation policy, reclaim only identified disposable material, then verify available bytes and core service health. Docker daemon log defaults apply to newly created containers; verify each existing container's effective logging configuration separately.

This off-box monitor can detect loss of the watched host, but it cannot run while the monitoring Mac is asleep or disconnected. Host-local limits, a local systemd timer, and a second independent always-on observer must be verified before claiming continuous coverage.
