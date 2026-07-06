"""Tests for Plan 20 operator-push commands and Plan 05 customer validation AC.

Covers:
- backup push: local log always written; remote skipped when no grant
- fleet push: local-only simulated push
- customer validate: core_errors vs profile_warnings are distinct classes in output
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.customer import customer_validate, format_customer_result
from genomes_agentic_os.update_ops import (
    backup_restore_plan,
    backup_run,
    backup_push,
    fleet_push,
    update_register,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registered_root(tmp_path: Path) -> Path:
    """Return a fully registered OS root (license active, grant written)."""
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    # Activate license
    assert main(["license", "activate", "--root", str(root), "--key", "test-key-1234"]) == 0
    # Register (writes grant + SSH keys)
    assert main(["update", "register", "--root", str(root)]) == 0
    return root


def _make_bare_root(tmp_path: Path) -> Path:
    """Return an OS root with no license or grant."""
    root = tmp_path / "agentic_os_bare"
    assert main(["init", "--target", str(root)]) == 0
    return root


# ---------------------------------------------------------------------------
# D1: backup push — always logs locally
# ---------------------------------------------------------------------------

class TestBackupPush:
    def test_backup_push_skips_remote_when_no_grant(self, tmp_path: Path) -> None:
        root = _make_bare_root(tmp_path)
        result = backup_push(root)
        assert result["remote_skipped"] is True
        assert "skip_reason" in result
        # Log file was still written
        assert Path(result["log_path"]).is_file()

    def test_backup_push_log_content_when_skipped(self, tmp_path: Path) -> None:
        root = _make_bare_root(tmp_path)
        result = backup_push(root)
        log_data = yaml.safe_load(Path(result["log_path"]).read_text(encoding="utf-8"))
        assert log_data["remote_skipped"] is True
        assert log_data["status"] == "skipped_no_grant"

    def test_backup_push_with_grant_records_remote(self, tmp_path: Path) -> None:
        root = _make_registered_root(tmp_path)
        result = backup_push(root)
        assert result["remote_skipped"] is False
        assert "remote" in result
        assert result["status"] == "pushed"
        assert Path(result["log_path"]).is_file()

    def test_backup_push_cli_exits_zero_no_grant(self, tmp_path: Path) -> None:
        root = _make_bare_root(tmp_path)
        # Should exit 0 even when remote is skipped — the push itself succeeded locally
        exit_code = main(["backup", "push", "--root", str(root)])
        assert exit_code == 0

    def test_backup_push_cli_exits_zero_with_grant(self, tmp_path: Path) -> None:
        root = _make_registered_root(tmp_path)
        exit_code = main(["backup", "push", "--root", str(root)])
        assert exit_code == 0


class TestBackupRestorePlan:
    def test_restore_plan_ready_after_registered_backup_run(self, tmp_path: Path) -> None:
        root = _make_registered_root(tmp_path)
        backup = backup_run(root, dry_run=True)

        result = backup_restore_plan(root)

        assert result["status"] == "ready"
        assert result["mutated"] is False
        assert result["latest_backup_log"] == backup["log_path"]
        assert ".agentic_root" in result["include"]
        assert "harness/security/ssh/*" in result["exclude"]
        assert result["coverage"]["status"] == "covered"
        assert "harness/bin/" in result["coverage"]["covered_critical_paths"]
        assert not result["coverage"]["missing_critical_paths"]
        assert result["steps"]

    def test_restore_plan_blocks_without_grant_or_backup_log(self, tmp_path: Path) -> None:
        root = _make_bare_root(tmp_path)

        result = backup_restore_plan(root)

        assert result["status"] == "blocked"
        assert result["mutated"] is False
        assert result["latest_backup_log"] == ""
        assert result["blockers"]

    def test_restore_plan_blocks_when_policy_misses_harness_commands(self, tmp_path: Path) -> None:
        root = _make_registered_root(tmp_path)
        policy_path = root / "harness" / "registries" / "backup-policy.yml"
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        policy["backup_policy"]["include"] = [
            ".agentic_root",
            "harness/AGENTS.md",
            "harness/registries/",
        ]
        policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
        backup_run(root, dry_run=True)

        result = backup_restore_plan(root)

        assert result["status"] == "blocked"
        assert result["coverage"]["status"] == "incomplete"
        assert "harness/bin/" in result["coverage"]["missing_critical_paths"]
        assert any("backup policy missing critical" in blocker for blocker in result["blockers"])

    def test_restore_plan_cli_exits_zero(self, tmp_path: Path) -> None:
        root = _make_registered_root(tmp_path)
        backup_run(root, dry_run=True)

        exit_code = main(["backup", "restore-plan", "--root", str(root)])

        assert exit_code == 0


# ---------------------------------------------------------------------------
# D2: fleet push — local-only simulated operator push
# ---------------------------------------------------------------------------

class TestFleetPush:
    def test_fleet_push_returns_structured_result(self) -> None:
        result = fleet_push("acme_corp")
        assert result["customer_slug"] == "acme_corp"
        assert result["provider"] == "fake_local"
        assert result["status"] == "recorded"
        assert "created_at" in result
        assert "note" in result

    def test_fleet_push_default_source(self) -> None:
        result = fleet_push("test_customer")
        assert result["source"] == "latest"

    def test_fleet_push_custom_source(self) -> None:
        result = fleet_push("test_customer", source="v1.2.3")
        assert result["source"] == "v1.2.3"

    def test_fleet_push_invalid_slug_raises(self) -> None:
        with pytest.raises(ValueError, match="snake_case"):
            fleet_push("")

    def test_fleet_push_cli_exits_zero(self, tmp_path: Path) -> None:
        exit_code = main(["fleet", "push", "my_customer"])
        assert exit_code == 0

    def test_fleet_push_cli_with_source_flag(self, tmp_path: Path) -> None:
        exit_code = main(["fleet", "push", "my_customer", "--source", "v2.0"])
        assert exit_code == 0


# ---------------------------------------------------------------------------
# D3: Plan 05 AC — customer validate distinguishes core_errors vs profile_warnings
# ---------------------------------------------------------------------------

class TestCustomerValidateSplit:
    def _minimal_customer_profile(self, tmp_path: Path, slug: str) -> Path:
        """Write a minimal customer.yml that passes slug validation."""
        profile = tmp_path / "customer.yml"
        profile.write_text(
            yaml.safe_dump(
                {"customer": {"slug": slug, "approved_domains": ["operations"]}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return profile

    def test_missing_root_returns_core_error_not_warning(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        result = customer_validate(nonexistent)
        assert result["ok"] is False
        assert len(result["core_errors"]) > 0
        # Missing root is always a core error, not a profile warning
        assert any("missing root" in e for e in result["core_errors"])
        # profile_warnings key must exist (even if empty)
        assert "profile_warnings" in result

    def test_fresh_customer_init_has_no_core_errors(self, tmp_path: Path) -> None:
        """A freshly inited customer OS should pass with ok=True."""
        profile = self._minimal_customer_profile(tmp_path, "test_co")
        target = tmp_path / "customer_root"
        assert main(["customer", "init", "test_co", "--profile", str(profile), "--target", str(target)]) == 0
        result = customer_validate(target)
        assert result["ok"] is True, f"core_errors: {result['core_errors']}"
        assert result["core_errors"] == []

    def test_profile_warnings_do_not_set_ok_false(self, tmp_path: Path) -> None:
        """Profile warnings (empty notion_workspace etc.) must NOT set ok=False."""
        profile = self._minimal_customer_profile(tmp_path, "warning_co")
        target = tmp_path / "warning_root"
        assert main(["customer", "init", "warning_co", "--profile", str(profile), "--target", str(target)]) == 0
        result = customer_validate(target)
        # notion_workspace is empty → profile warning
        assert any("notion_workspace" in w for w in result["profile_warnings"])
        # But ok must remain True — warnings are advisory
        assert result["ok"] is True

    def test_format_output_labels_both_classes(self, tmp_path: Path) -> None:
        """format_customer_result must clearly label core_errors and profile_warnings."""
        nonexistent = tmp_path / "nowhere"
        result = customer_validate(nonexistent)
        output = format_customer_result(result)
        assert "core_errors:" in output
        assert "profile_warnings:" in output
        # The comment distinguishing the two classes must be present
        assert "ok=false" in output.lower() or "OS failures" in output

    def test_format_output_for_clean_root(self, tmp_path: Path) -> None:
        """format_customer_result on a clean init must show both sections with 0 counts."""
        profile = self._minimal_customer_profile(tmp_path, "clean_co")
        target = tmp_path / "clean_root"
        assert main(["customer", "init", "clean_co", "--profile", str(profile), "--target", str(target)]) == 0
        result = customer_validate(target)
        output = format_customer_result(result)
        assert "core_errors: 0" in output
        assert "profile_warnings:" in output

    def test_cli_customer_validate_exits_1_on_core_error(self, tmp_path: Path) -> None:
        """CLI must exit 1 when core_errors exist."""
        nonexistent = tmp_path / "no_such_root"
        exit_code = main(["customer", "validate", "--root", str(nonexistent)])
        assert exit_code == 1

    def test_cli_customer_validate_exits_0_on_warnings_only(self, tmp_path: Path) -> None:
        """CLI must exit 0 when only profile_warnings exist (ok=True)."""
        profile = self._minimal_customer_profile(tmp_path, "warn_only")
        target = tmp_path / "warn_root"
        assert main(["customer", "init", "warn_only", "--profile", str(profile), "--target", str(target)]) == 0
        exit_code = main(["customer", "validate", "--root", str(target)])
        assert exit_code == 0
