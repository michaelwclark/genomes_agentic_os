"""Tests for F-012 (metrics refresh), F-014 (routing suggestion), F-021 (name errors).

Covers:
- metrics_refresh: writes scorecard.yml with expected keys; works on empty root
- RoutingSuggestion: low-confidence multi-match returns suggestion, not hard error
- validate_name: hyphenated names suggest the snake_case form
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.metrics_ops import metrics_refresh
from genomes_agentic_os.routing import RoutingSuggestion, detect_from_request, route_request
from genomes_agentic_os.scaffold import validate_name


# ---------------------------------------------------------------------------
# F-021: validate_name hyphen suggestion
# ---------------------------------------------------------------------------

class TestValidateNameHyphenSuggestion:
    def test_valid_snake_case_passes(self) -> None:
        assert validate_name("weekly_report") == "weekly_report"

    def test_hyphenated_name_raises_with_suggestion(self) -> None:
        with pytest.raises(ValueError, match="weekly_report") as exc_info:
            validate_name("weekly-report")
        # The suggestion must be present in the error message
        assert "did you mean" in str(exc_info.value)
        assert "'weekly_report'" in str(exc_info.value)

    def test_multi_hyphen_name_suggests_snake(self) -> None:
        with pytest.raises(ValueError, match="my_long_name"):
            validate_name("my-long-name")

    def test_trailing_hyphen_raises_without_suggestion(self) -> None:
        """A trailing hyphen produces 'name_' which fails the pattern — no suggestion."""
        with pytest.raises(ValueError):
            validate_name("bad-name-")

    def test_uppercase_raises_no_suggestion(self) -> None:
        """Uppercase is not fixable by replacing hyphens — no suggestion clause."""
        with pytest.raises(ValueError) as exc_info:
            validate_name("MyName")
        # No 'did you mean' since replacing hyphens doesn't fix it
        assert "did you mean" not in str(exc_info.value)

    def test_label_appears_in_error(self) -> None:
        with pytest.raises(ValueError, match="workflow_name"):
            validate_name("my-workflow", "workflow_name")


# ---------------------------------------------------------------------------
# F-014: routing low-confidence suggestion
# ---------------------------------------------------------------------------

class TestRoutingSuggestion:
    def _init_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "agentic_os"
        assert main(["init", "--target", str(root)]) == 0
        return root

    def test_suggestion_is_subclass_of_value_error(self) -> None:
        """RoutingSuggestion must be catch-able as ValueError for backward compatibility."""
        exc = RoutingSuggestion({"domain": "personal"}, "low confidence")
        assert isinstance(exc, ValueError)

    def test_suggestion_carries_best_candidate(self) -> None:
        exc = RoutingSuggestion({"domain": "los", "project": "auth"}, "multiple projects matched")
        assert exc.suggestion["domain"] == "los"
        assert exc.suggestion["project"] == "auth"
        assert "multiple projects" in exc.reason

    def test_no_match_still_raises_hard_value_error(self, tmp_path: Path) -> None:
        """A completely unrecognised request must still raise ValueError (exit 2)."""
        root = self._init_root(tmp_path)
        with pytest.raises(ValueError):
            detect_from_request(root, "zzz_completely_unrecognised_xyzzy")

    def test_route_request_no_match_exits_2(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        assert main(["route", "zzz_completely_unrecognised", "--root", str(root)]) == 2

    def test_route_request_multi_domain_exits_0_with_suggestion(self, tmp_path: Path) -> None:
        """Multi-domain match now returns a suggestion packet (exit 0), not a hard refusal."""
        root = self._init_root(tmp_path)
        exit_code = main(["route", "Compare los and personal work", "--root", str(root)])
        assert exit_code == 0

    def test_route_request_suggestion_appears_in_known_gaps(self, tmp_path: Path) -> None:
        """The SUGGESTION label must appear in known_gaps so the caller can see it."""
        root = self._init_root(tmp_path)
        packet = route_request(root, "Compare los and personal work")
        suggestion_gaps = [g for g in packet.known_gaps if "SUGGESTION" in g]
        assert len(suggestion_gaps) >= 1
        assert "low confidence" in suggestion_gaps[0]

    def test_approval_risks_still_computed_on_suggestion(self, tmp_path: Path) -> None:
        """Even on a suggestion path, approval_risks must be evaluated."""
        root = self._init_root(tmp_path)
        # 'send' triggers 'external write' risk
        packet = route_request(root, "send los and personal summary to customer")
        assert "external write" in packet.approval_risks

    def test_single_domain_match_is_hard_route_not_suggestion(self, tmp_path: Path) -> None:
        """A clear single-domain match must not be a suggestion."""
        root = self._init_root(tmp_path)
        packet = route_request(root, "personal task")
        suggestion_gaps = [g for g in packet.known_gaps if "SUGGESTION" in g]
        assert len(suggestion_gaps) == 0


# ---------------------------------------------------------------------------
# F-012: metrics refresh
# ---------------------------------------------------------------------------

class TestMetricsRefresh:
    def _init_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "agentic_os"
        assert main(["init", "--target", str(root)]) == 0
        return root

    def test_refresh_creates_scorecard_file(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        result = metrics_refresh(root)
        assert "scorecard_path" in result
        scorecard_path = Path(result["scorecard_path"])
        assert scorecard_path.is_file()
        assert scorecard_path.name == "scorecard.yml"

    def test_scorecard_has_required_top_level_keys(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        result = metrics_refresh(root)
        required = {"schema_version", "root", "run_health", "automation_maturity", "doctor_findings"}
        assert required.issubset(result.keys())

    def test_scorecard_run_health_structure(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        result = metrics_refresh(root)
        rh = result["run_health"]
        assert "total_runs" in rh
        assert "done" in rh
        assert "failed" in rh
        assert "success_rate" in rh

    def test_scorecard_automation_maturity_structure(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        result = metrics_refresh(root)
        am = result["automation_maturity"]
        assert "total" in am
        assert "by_level" in am
        assert "advanced_fraction" in am
        # All maturity levels must be present even if zero
        for level in ("observe", "prepare", "propose", "execute_approved", "execute_guarded"):
            assert level in am["by_level"]

    def test_empty_root_produces_zero_counts(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        result = metrics_refresh(root)
        assert result["run_health"]["total_runs"] == 0
        assert result["automation_maturity"]["total"] == 0
        assert result["automation_maturity"]["advanced_fraction"] == 0.0

    def test_scorecard_is_valid_yaml(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        result = metrics_refresh(root)
        scorecard_path = Path(result["scorecard_path"])
        data = yaml.safe_load(scorecard_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["schema_version"] == 1

    def test_refresh_is_idempotent(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        result1 = metrics_refresh(root)
        result2 = metrics_refresh(root)
        # Both calls succeed and produce a scorecard
        assert Path(result1["scorecard_path"]).is_file()
        assert Path(result2["scorecard_path"]).is_file()

    def test_cli_metrics_refresh_exits_zero(self, tmp_path: Path) -> None:
        root = self._init_root(tmp_path)
        exit_code = main(["metrics", "refresh", "--root", str(root)])
        assert exit_code == 0

    def test_refresh_with_run_logs_counts_them(self, tmp_path: Path) -> None:
        """Synthetic run logs should appear in the scorecard totals."""
        root = self._init_root(tmp_path)
        # Create a synthetic done run log in the expected path
        from genomes_agentic_os.scaffold import shared_factory_path
        runs_dir = shared_factory_path(root, "06-runs-and-logs", "runs")
        runs_dir.mkdir(parents=True, exist_ok=True)
        import yaml as _yaml
        (runs_dir / "run-20260101.yml").write_text(
            _yaml.safe_dump({"status": "done", "domain": "personal"}), encoding="utf-8"
        )
        (runs_dir / "run-20260102.yml").write_text(
            _yaml.safe_dump({"status": "failed", "domain": "personal"}), encoding="utf-8"
        )
        result = metrics_refresh(root)
        assert result["run_health"]["total_runs"] == 2
        assert result["run_health"]["done"] == 1
        assert result["run_health"]["failed"] == 1
        assert result["run_health"]["success_rate"] == 0.5
