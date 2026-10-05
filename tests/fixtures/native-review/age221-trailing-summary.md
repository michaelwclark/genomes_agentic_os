```json
[
  {
    "id": "F1",
    "severity": "medium",
    "category": "tests",
    "file": "tests/test_execution_fabric_deployment_assets.py",
    "line": 1878,
    "title": "inherited_live_runtime cannot fail for the Linux activation test, so that call site has no regression guard",
    "detail": "test_linux_activation_is_explicit_preflight_gated_and_repeatable binds the fixture, but every variable the fixture poisons is neutralised before it can reach activate-linux.sh. The test passes its own \"FABRIC_RUNTIME_ENV_FILE\": str(runtime_env) at line 1920, which wins over the fixture's value because it appears later in the dict literal. installers/execution-fabric/bin/_lib.sh:18-22 then does `set -a; . \"$FABRIC_RUNTIME_ENV_FILE\"; set +a`, and the test's runtime.env re-assigns FABRIC_OS_ROOT and FABRIC_RUNTIME_STATE_DIR (lines 1896-1899), overwriting the fixture's live_root values. WITNESS_ENV_FILE, FABRIC_API_TOKEN_FILE, AGENTIC_OS_ROOT and AGENTIC_OS_EXECUTION_FABRIC_API_BASE are never read by activate-linux.sh or _lib.sh, and HOME is only consulted by fabric_runtime_env_default() on Darwin when FABRIC_RUNTIME_ENV_FILE is unset. Consequence: reverting line 1916 from _isolated_environment(tmp_path) back to {**os.environ, ...} leaves both teardown assertions (lines 83-84) satisfied and the test green. The PR's Validation claim that \"a negative control restoring inherited-environment behavior ... is rejected by the regression fixture\" holds only via the three macOS tests (B/C/D), which do not set FABRIC_RUNTIME_ENV_FILE and therefore do source the poisoned file; the Linux call site is unprotected.",
    "suggested_fix": "Add \"FABRIC_LOS_SECURITY_SCHEDULES_ENABLED\": \"true\" to the fixture's monkeypatch.setenv block (lines 71-81). activate-linux.sh:63 reads it as ${FABRIC_LOS_SECURITY_SCHEDULES_ENABLED:-false} *after* fabric_load_runtime returns, and the Linux test's runtime.env does not set it, so it is the one fixture-settable variable the sourced file cannot clobber. Under isolation the var is never forwarded (test stays green); under the negative control activation reaches the reconciler check at activate-linux.sh:64-74 and exits 69, failing the test.",
    "blocking": false
  },
  {
    "id": "F2",
    "severity": "medium",
    "category": "tests",
    "file": "tests/test_execution_fabric_deployment_assets.py",
    "line": 65,
    "title": "Poisoned runtime.env exercises only the code-execution half of the stated threat model, not PATH hijack",
    "detail": "The PR body names two hazards: an inherited runtime file could \"execute shell statements or replace mocked service-command paths.\" The fixture's runtime.env (lines 65-69) covers the first via `printf 'backend: changed' > <backend>` plus FABRIC_LOS_SECURITY_WORKER_ENABLED=true, but contains no PATH= assignment, so the second hazard has no negative control. Both activators would honour one: activate-macos.sh:28-31 sources the file with a plain `.` before resolving `id` (line 37) and `launchctl` (lines 42, 65-70), and _lib.sh:18-22 uses `set -a` so a sourced PATH is exported before activate-linux.sh invokes `systemctl` (lines 54-58). A sourced `PATH=` would therefore replace the fake_bin shims the tests rely on and let activation reach the host's real service manager — exactly the failure mode the ticket exists to prevent — yet no assertion in this PR would notice.",
    "suggested_fix": "Add a `PATH={live_root}/nonexistent-bin` line to the fixture's runtime.env at line 66. Detection comes from the test bodies rather than the teardown byte-compare: the fake systemctl/launchctl/uname/id shims stop resolving, so the activation-log assertions fail under the negative control while the isolated runs are unaffected (the file is never sourced).",
    "blocking": false
  },
  {
    "id": "F3",
    "severity": "low",
    "category": "tests",
    "file": "tests/test_execution_fabric_deployment_assets.py",
    "line": 1869,
    "title": "Environment isolation applied to `sh -n` is a no-op",
    "detail": "test_shell_assets_are_syntax_valid was given a tmp_path parameter (line 1853) solely to pass env=_isolated_environment(tmp_path) to `sh -n` (lines 1869-1873). `sh -n` parses without executing, so no environment variable can affect the outcome; the change adds a fixture dependency and runs two mkdir calls per script across the ~30 scripts the test iterates, for zero isolation benefit. It also makes the helper look load-bearing at a site where it is not, which obscures where isolation actually matters.",
    "suggested_fix": "Revert this hunk: drop the tmp_path parameter and the env= argument, restoring `subprocess.run([\"sh\", \"-n\", str(script)], check=True)`.",
    "blocking": false
  },
  {
    "id": "F4",
    "severity": "low",
    "category": "tests",
    "file": "tests/test_execution_fabric_backup_health.py",
    "line": 124,
    "title": "Adjacent (pre-existing, out-of-scope) Fabric script test still inherits the operator environment",
    "detail": "NOT INTRODUCED BY THIS PR and outside its stated change scope (\"one test module\") — recorded for follow-up only, not as a merge gate. test_validator_accepts_hash_bound_restore_manifest_and_rejects_tampering builds env = {**os.environ, \"FABRIC_RUNTIME_ENV_FILE\": str(runtime)} and runs validate-backup-health-receipt.sh. The explicit FABRIC_RUNTIME_ENV_FILE closes the main hazard, but installers/execution-fabric/bin/validate-backup-health-receipt.sh:64 reads ${FABRIC_BACKUP_HEALTH_RECEIPT_MAX_AGE_SECONDS:-86400} after fabric_load_runtime, and the test's runtime.env does not set it, so an operator export of that variable leaks into the run and can flip the assertion either way (a small value rejects the fresh receipt; a large value masks staleness).",
    "suggested_fix": "In a follow-up, reuse the same allowlist approach — either move _isolated_environment into a shared tests/ helper and use it here, or pin FABRIC_BACKUP_HEALTH_RECEIPT_MAX_AGE_SECONDS explicitly in the test's runtime.env.",
    "blocking": false
  }
]
```

AGENTIC_OS_REVIEW_VERDICT: FINDINGS

**Summary of what I verified (no findings filed):**
- All 35 `subprocess.*` call sites in the modified module now pass an explicit `env=` — none inherit `os.environ`. Verified by count (36 `subprocess.` references incl. the import, 35 `env=` kwargs) and by reading each hunk.
- `PATH` override ordering is correct at every fake-bin site: `**_isolated_environment(tmp_path)` always precedes the explicit `"PATH": f"{fake_bin}:{os.environ['PATH']}"` key.
- Variables that scripts genuinely need are re-supplied where stripped: `REAL_PYTHON`/`FABRIC_WORKER_PYTHON`/`FABRIC_AGENTIC_OS_*` (line 1565+), `PYTHONPATH` (line 2410), `FABRIC_SECRETS_DIR`, `WITNESS_ENV_FILE`.
- The "stripping `os.environ` dropped something a script needed" class is closed empirically by the PR's recorded validation (full suite plus deployment-assets under 3.14.6 and 3.11.15 at this exact head) and CI green.
- `test_los_security_schedule_reconciler_is_dry_run_by_default` imports the shipped reconciler in-process, but monkeypatches `_request` and passes `--api-base`/token files explicitly, so it cannot reach a live fabric.
- The fixture teardown comparison at line 83 is correct (it re-reads the keys of `before`), and `monkeypatch` teardown ordering means the assertions run before env restoration.

The acceptance criterion — installer/activation subprocesses no longer inherit the operator's Fabric runtime — **is met**. F1 and F2 are gaps in the *regression guard's* coverage, not in the isolation itself. Nothing here blocks merge.
