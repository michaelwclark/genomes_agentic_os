"""Tests for plans 12 and 14 factory-playbook deliverables.

Covers:
  - Private-name scrub check (plan-12 AC4, plan-14 AC5)
  - Operator-room generation + no-default-domains (plan-12 AC2, AC3)
  - Room CONTEXT.md load-contract fields (plan-12 AC3)
  - Brief scaffold happy path + refuse-overwrite (plan-14 AC1)
  - Skills non-stub (plan-14 AC1–AC4)
  - Template section completeness (plan-14 AC2)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.customer import (
    PRIVATE_TERMS,
    customer_init,
    private_term_warnings,
    scaffold_customer_brief,
)
from genomes_agentic_os.room_profile import install_profile_os
from genomes_agentic_os.scaffold import DEFAULT_DOMAINS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_customer_profile() -> dict[str, Any]:
    """A neutral customer profile that contains no private-source terms."""
    return {
        "customer": {
            "slug": "neutral_co",
            "display_name": "Neutral Co",
            "owner": "Operations Lead",
            "notion_workspace": "Neutral Workspace",
            "approved_domains": ["operations"],
            "source_systems": [{"name": "helpdesk", "role": "support inbox"}],
            "default_workflows": [],
            "default_automations": [],
            "approval_policy": {
                "external_writes_require_approval": True,
                "customer_visible_output_requires_approval": True,
            },
        }
    }


def _write_customer_profile(path: Path, data: dict[str, Any] | None = None) -> None:
    if data is None:
        data = _minimal_customer_profile()
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _three_room_profile() -> str:
    """Profile with 3 operator-named rooms. None are DEFAULT_DOMAINS slugs."""
    return """\
os:
  display_name: Studio OS
  owner: Operator
approval_policy:
  external_writes_require_approval: true
rooms:
  - slug: intake_room
    display_name: Intake Room
    purpose: New requests are captured and triaged.
    inputs:
      - email requests
      - form submissions
    output_folders:
      triage: triage
    routing:
      - task: triage request
        read_first:
          - docs/triage-rules.md
        read_when_needed:
          - docs/escalation-guide.md
        skip_by_default:
          - archive
        output_path: triage/
    tools:
      - name: os-navigator
        trigger: start of session
        notes: route to correct room first
    done_means:
      - request is filed in triage
      - source is recorded
  - slug: production_room
    display_name: Production Room
    purpose: Approved work is executed and delivered.
    inputs:
      - approved triage items
    output_folders:
      outputs: outputs
    routing:
      - task: execute approved work
        read_first:
          - RULES.md
        read_when_needed:
          - docs/style-guide.md
        skip_by_default:
          - draft docs
        output_path: outputs/
    tools: []
    done_means:
      - output is in outputs folder
      - approval is recorded
  - slug: review_room
    display_name: Review Room
    purpose: Outputs are reviewed before delivery.
    inputs:
      - production outputs
    output_folders:
      reviewed: reviewed
    routing:
      - task: review output
        read_first:
          - RULES.md
        read_when_needed: []
        skip_by_default:
          - raw drafts
        output_path: reviewed/
    tools: []
    done_means:
      - reviewer approval is recorded
"""


def _five_room_profile() -> str:
    """Profile with 5 operator-named rooms."""
    base = yaml.safe_load(_three_room_profile())
    base["rooms"].extend(
        [
            {
                "slug": "archive_intake",
                "display_name": "Archive Intake",
                "purpose": "Old items are filed.",
                "inputs": ["closed items"],
                "output_folders": {"filed": "filed"},
                "routing": [{"task": "file item", "read_first": ["RULES.md"], "read_when_needed": [], "skip_by_default": [], "output_path": "filed/"}],
                "tools": [],
                "done_means": ["item is filed"],
                "approvals": {"external_writes_require_approval": True},
            },
            {
                "slug": "reporting_room",
                "display_name": "Reporting Room",
                "purpose": "Metrics and reports are produced.",
                "inputs": ["production outputs", "run logs"],
                "output_folders": {"reports": "reports"},
                "routing": [{"task": "produce report", "read_first": ["RULES.md"], "read_when_needed": ["docs/metrics.md"], "skip_by_default": [], "output_path": "reports/"}],
                "tools": [],
                "done_means": ["report is in reports folder"],
                "approvals": {"external_writes_require_approval": True},
            },
        ]
    )
    return yaml.safe_dump(base, sort_keys=False)


# ---------------------------------------------------------------------------
# 1. Private-name scrub check
# ---------------------------------------------------------------------------


class TestPrivateTermScrub:
    def test_private_terms_list_includes_eduba(self) -> None:
        """eduba is a course-platform name from factory school material."""
        assert "eduba" in PRIVATE_TERMS

    def test_private_terms_list_includes_genome_and_clark(self) -> None:
        assert "genome" in PRIVATE_TERMS
        assert "clark" in PRIVATE_TERMS

    def test_private_terms_list_includes_clarks_consulting_slug(self) -> None:
        assert "clarks_consulting" in PRIVATE_TERMS

    def test_private_terms_list_includes_los_and_lenders(self) -> None:
        assert "los" in PRIVATE_TERMS
        assert "lenders" in PRIVATE_TERMS

    def test_neutral_customer_install_has_no_private_terms(self, tmp_path: Path) -> None:
        """A fresh customer install from a neutral profile must produce zero private-term warnings."""
        profile = tmp_path / "profile.yml"
        root = tmp_path / "customer_root"
        _write_customer_profile(profile)
        customer_init("neutral_co", profile, root)

        warnings = private_term_warnings(root)
        # Filter out any warnings that reference the installed customer.yml itself —
        # the profile slug "neutral_co" and display name "Neutral Co" contain no
        # private terms, so the warning list should be empty.
        assert warnings == [], (
            f"private-term warnings found in neutral install:\n" + "\n".join(warnings)
        )

    def test_private_term_warnings_detects_genome_in_content(self, tmp_path: Path) -> None:
        """private_term_warnings must catch the term 'genome' in a generated file."""
        bad_file = tmp_path / "test.md"
        bad_file.write_text("# Notes\n\nThis belongs to genome.\n", encoding="utf-8")
        warnings = private_term_warnings(tmp_path)
        assert any("genome" in w for w in warnings), f"Expected 'genome' warning, got: {warnings}"

    def test_private_term_warnings_detects_eduba(self, tmp_path: Path) -> None:
        """eduba must be flagged as a private term in generated content."""
        bad_file = tmp_path / "test.yml"
        bad_file.write_text("platform: eduba\n", encoding="utf-8")
        warnings = private_term_warnings(tmp_path)
        assert any("eduba" in w for w in warnings), f"Expected 'eduba' warning, got: {warnings}"

    def test_private_term_warnings_word_boundary(self, tmp_path: Path) -> None:
        """'los_domain' should NOT be flagged — 'los' only matches as a whole word."""
        safe_file = tmp_path / "test.md"
        safe_file.write_text("# Notes\n\nDomain: los_domain\nURL: https://example.com/close\n", encoding="utf-8")
        warnings = private_term_warnings(tmp_path)
        assert warnings == [], f"Unexpected word-boundary false positive: {warnings}"

    def test_three_room_profile_context_md_has_no_private_terms(self, tmp_path: Path) -> None:
        """Room CONTEXT.md files generated from a neutral profile must not contain private terms.

        Scope: only the generated CONTEXT.md for each room (not TOOLS.md or harness docs,
        which legitimately reference 'Genome's Agentic OS' — room-profile installs are
        personal OS installs where operator metadata is expected and correct).
        The private-term scrub is a customer-OS-level gate.  Here we verify that
        profile-generated room context content does not accidentally copy private names.
        """
        import re

        profile_path = tmp_path / "profile.yml"
        profile_path.write_text(_three_room_profile(), encoding="utf-8")
        root = tmp_path / "studio_os"
        result = install_profile_os(root, profile_path)

        for room_slug in result["rooms"]:
            context_path = root / room_slug / "CONTEXT.md"
            assert context_path.is_file(), f"{room_slug}/CONTEXT.md missing"
            content = context_path.read_text(encoding="utf-8").lower()
            for term in PRIVATE_TERMS:
                match = re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", content)
                assert not match, (
                    f"Private term '{term}' found in {room_slug}/CONTEXT.md"
                )


# ---------------------------------------------------------------------------
# 2. Operator-room generation + no-default-domains
# ---------------------------------------------------------------------------


class TestOperatorRoomGeneration:
    def test_three_room_profile_creates_exactly_three_rooms(self, tmp_path: Path) -> None:
        """3-room profile must produce exactly those 3 rooms."""
        profile_path = tmp_path / "profile.yml"
        profile_path.write_text(_three_room_profile(), encoding="utf-8")
        root = tmp_path / "studio_os"

        result = install_profile_os(root, profile_path)
        assert sorted(result["rooms"]) == sorted(["intake_room", "production_room", "review_room"])

    def test_five_room_profile_creates_exactly_five_rooms(self, tmp_path: Path) -> None:
        """5-room profile must produce exactly those 5 rooms."""
        profile_path = tmp_path / "profile.yml"
        profile_path.write_text(_five_room_profile(), encoding="utf-8")
        root = tmp_path / "studio_os"

        result = install_profile_os(root, profile_path)
        expected = {"intake_room", "production_room", "review_room", "archive_intake", "reporting_room"}
        assert set(result["rooms"]) == expected

    def test_operator_rooms_do_not_create_default_domains(self, tmp_path: Path) -> None:
        """No DEFAULT_DOMAINS directory must be created by a room-profile install."""
        profile_path = tmp_path / "profile.yml"
        profile_path.write_text(_three_room_profile(), encoding="utf-8")
        root = tmp_path / "studio_os"
        install_profile_os(root, profile_path)

        for domain in DEFAULT_DOMAINS:
            assert not (root / domain).exists(), (
                f"DEFAULT_DOMAIN '{domain}' was created but should not exist in a room-profile install"
            )

    def test_operator_rooms_context_md_exists(self, tmp_path: Path) -> None:
        """Each operator-named room must have a CONTEXT.md."""
        profile_path = tmp_path / "profile.yml"
        profile_path.write_text(_three_room_profile(), encoding="utf-8")
        root = tmp_path / "studio_os"
        install_profile_os(root, profile_path)

        for slug in ("intake_room", "production_room", "review_room"):
            assert (root / slug / "CONTEXT.md").is_file(), f"{slug}/CONTEXT.md missing"


# ---------------------------------------------------------------------------
# 3. Room CONTEXT.md load-contract fields
# ---------------------------------------------------------------------------


class TestRoomContextLoadContract:
    def _get_context(self, tmp_path: Path, room_slug: str = "intake_room") -> str:
        profile_path = tmp_path / "profile.yml"
        profile_path.write_text(_three_room_profile(), encoding="utf-8")
        root = tmp_path / "studio_os"
        install_profile_os(root, profile_path)
        return (root / room_slug / "CONTEXT.md").read_text(encoding="utf-8")

    def test_context_has_read_first_section(self, tmp_path: Path) -> None:
        content = self._get_context(tmp_path)
        assert "## Read First" in content

    def test_context_has_read_when_needed_section(self, tmp_path: Path) -> None:
        content = self._get_context(tmp_path)
        assert "## Read When Needed" in content

    def test_context_has_do_not_load_section(self, tmp_path: Path) -> None:
        content = self._get_context(tmp_path)
        assert "## Do Not Load By Default" in content

    def test_context_has_tools_and_skills_section(self, tmp_path: Path) -> None:
        content = self._get_context(tmp_path)
        assert "## Tools And Skills" in content

    def test_context_has_output_folders_section(self, tmp_path: Path) -> None:
        content = self._get_context(tmp_path)
        assert "## Output Folders" in content

    def test_context_has_done_means_section(self, tmp_path: Path) -> None:
        content = self._get_context(tmp_path)
        assert "## Done Means" in content

    def test_context_read_first_includes_standard_files(self, tmp_path: Path) -> None:
        """Read First must include at minimum ROUTER.md, RULES.md, TOOLS.md."""
        content = self._get_context(tmp_path)
        assert "ROUTER.md" in content
        assert "RULES.md" in content
        assert "TOOLS.md" in content

    def test_context_profile_data_flows_into_read_first(self, tmp_path: Path) -> None:
        """Profile read_first items flow into the Read First section."""
        content = self._get_context(tmp_path)
        assert "docs/triage-rules.md" in content

    def test_context_profile_data_flows_into_read_when_needed(self, tmp_path: Path) -> None:
        """Profile read_when_needed items flow into the Read When Needed section."""
        content = self._get_context(tmp_path)
        assert "docs/escalation-guide.md" in content

    def test_context_profile_data_flows_into_skip_by_default(self, tmp_path: Path) -> None:
        """Profile skip_by_default items flow into the Do Not Load By Default section."""
        content = self._get_context(tmp_path)
        assert "archive" in content

    def test_context_done_means_content(self, tmp_path: Path) -> None:
        """Done Means must include profile-supplied criteria."""
        content = self._get_context(tmp_path)
        assert "request is filed in triage" in content

    def test_template_context_has_all_six_sections(self) -> None:
        """The static room/CONTEXT.md template must declare all six load-contract fields."""
        from genomes_agentic_os.scaffold import template_source_dir
        template = (template_source_dir() / "room" / "CONTEXT.md").read_text(encoding="utf-8")
        required_sections = [
            "## Read First",
            "## Read When Needed",
            "## Do Not Load By Default",
            "## Tools And Skills",
            "## Output Folders",
            "## Done Means",
        ]
        for section in required_sections:
            assert section in template, f"Missing section '{section}' in room/CONTEXT.md template"


# ---------------------------------------------------------------------------
# 4. Brief scaffold happy path + refuse-overwrite
# ---------------------------------------------------------------------------


class TestBriefScaffold:
    def _setup_customer(self, tmp_path: Path) -> Path:
        profile = tmp_path / "profile.yml"
        root = tmp_path / "customer_root"
        _write_customer_profile(profile)
        customer_init("neutral_co", profile, root)
        return root

    def test_brief_scaffold_creates_file(self, tmp_path: Path) -> None:
        root = self._setup_customer(tmp_path)
        result = scaffold_customer_brief(root, "operations", "invoice_sync")
        assert result["created"] is True
        path = Path(result["path"])
        assert path.is_file()
        assert path.name == "invoice_sync-brief.md"

    def test_brief_scaffold_file_location(self, tmp_path: Path) -> None:
        """Brief goes in <root>/<domain>/01-intake/<name>-brief.md."""
        root = self._setup_customer(tmp_path)
        result = scaffold_customer_brief(root, "operations", "invoice_sync")
        path = Path(result["path"])
        assert path.parent == root / "operations" / "01-intake"

    def test_brief_scaffold_contains_required_sections(self, tmp_path: Path) -> None:
        """The scaffolded brief must contain all required template sections."""
        root = self._setup_customer(tmp_path)
        result = scaffold_customer_brief(root, "operations", "invoice_sync")
        content = Path(result["path"]).read_text(encoding="utf-8")
        required_sections = [
            "## Outcome",
            "## Current Manual Workflow",
            "## Systems Involved",
            "## Inputs",
            "## Outputs",
            "## Frequency",
            "## Current Time Cost",
            "## Error Cost",
            "## Step Classification",
            "## Must Stay Manual",
            "## Automation Candidate Steps",
            "## Acceptance Criteria",
            "## Approval Gate",
            "## Rollback",
            "## Pilot Scope",
            "## Data Boundaries",
            "## Metrics Baseline",
        ]
        for section in required_sections:
            assert section in content, f"Missing section '{section}' in scaffolded brief"

    def test_brief_scaffold_substitutes_name(self, tmp_path: Path) -> None:
        """The placeholder <workflow_or_outcome> is replaced with the brief name."""
        root = self._setup_customer(tmp_path)
        result = scaffold_customer_brief(root, "operations", "invoice_sync")
        content = Path(result["path"]).read_text(encoding="utf-8")
        assert "<workflow_or_outcome>" not in content
        assert "Invoice Sync" in content

    def test_brief_scaffold_refuse_overwrite(self, tmp_path: Path) -> None:
        """Calling scaffold twice with the same name must return created=False and not change the file."""
        root = self._setup_customer(tmp_path)
        result1 = scaffold_customer_brief(root, "operations", "invoice_sync")
        path = Path(result1["path"])
        original_content = path.read_text(encoding="utf-8")
        # Overwrite file content manually
        path.write_text("# manually edited\n", encoding="utf-8")
        result2 = scaffold_customer_brief(root, "operations", "invoice_sync")
        assert result2["created"] is False
        assert result2["path"] == result1["path"]
        # Content must not be reset
        assert path.read_text(encoding="utf-8") == "# manually edited\n"

    def test_brief_scaffold_cli_happy_path(self, tmp_path: Path, capsys) -> None:
        """agentic-os customer brief must create a brief and print JSON with path and created."""
        import json

        profile = tmp_path / "profile.yml"
        root = tmp_path / "customer_root"
        _write_customer_profile(profile)
        customer_init("neutral_co", profile, root)

        exit_code = main(
            ["customer", "brief", "--root", str(root), "--domain", "operations", "--name", "email_routing"]
        )
        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["created"] is True
        assert "email_routing-brief.md" in output["path"]
        assert Path(output["path"]).is_file()

    def test_brief_scaffold_cli_refuse_overwrite(self, tmp_path: Path, capsys) -> None:
        """Second CLI invocation with same name must return created=False and exit 0."""
        import json

        profile = tmp_path / "profile.yml"
        root = tmp_path / "customer_root"
        _write_customer_profile(profile)
        customer_init("neutral_co", profile, root)

        main(["customer", "brief", "--root", str(root), "--domain", "operations", "--name", "email_routing"])
        capsys.readouterr()
        exit_code = main(
            ["customer", "brief", "--root", str(root), "--domain", "operations", "--name", "email_routing"]
        )
        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["created"] is False

    def test_brief_scaffold_rejects_private_domain_name(self, tmp_path: Path) -> None:
        """Brief scaffold must reject a domain slug that is a private term."""
        profile = tmp_path / "profile.yml"
        root = tmp_path / "customer_root"
        _write_customer_profile(profile)
        customer_init("neutral_co", profile, root)

        import pytest

        with pytest.raises(ValueError, match="private Genome source name"):
            scaffold_customer_brief(root, "los", "test_brief")


# ---------------------------------------------------------------------------
# 5. Skills non-stub check
# ---------------------------------------------------------------------------


class TestSkillsNonStub:
    """Each playbook skill must contain its key sections and be substantively longer than 17 lines."""

    SKILLS_DIR = Path(__file__).parent.parent / "harness" / "skills"

    def _skill_content(self, skill_name: str) -> str:
        path = self.SKILLS_DIR / skill_name / "SKILL.md"
        assert path.is_file(), f"{skill_name}/SKILL.md is missing"
        return path.read_text(encoding="utf-8")

    def _line_count(self, content: str) -> int:
        return len([line for line in content.splitlines() if line.strip()])

    def test_client_automation_brief_skill_not_stub(self) -> None:
        content = self._skill_content("client-automation-brief")
        assert self._line_count(content) > 30, "client-automation-brief SKILL.md is still a stub"

    def test_client_automation_brief_skill_has_discovery_questions(self) -> None:
        content = self._skill_content("client-automation-brief")
        assert "Discovery" in content or "discovery" in content

    def test_client_automation_brief_skill_has_layer_triage(self) -> None:
        content = self._skill_content("client-automation-brief")
        assert "Deterministic" in content
        assert "Rule-Based" in content or "Rule-based" in content
        assert "LLM-Needed" in content or "LLM-needed" in content
        assert "Human Judgment" in content or "Human judgment" in content

    def test_client_automation_brief_skill_has_fit_gate(self) -> None:
        content = self._skill_content("client-automation-brief")
        assert "Good first automation" in content or "good first automation" in content
        assert "Bad first automation" in content or "bad first automation" in content

    def test_client_automation_brief_skill_has_approval_gate(self) -> None:
        content = self._skill_content("client-automation-brief")
        assert "Approval" in content or "approval" in content

    def test_client_automation_brief_skill_names_brief_location(self) -> None:
        content = self._skill_content("client-automation-brief")
        assert "01-intake" in content

    def test_control_plane_bootstrap_skill_not_stub(self) -> None:
        content = self._skill_content("control-plane-bootstrap")
        assert self._line_count(content) > 30, "control-plane-bootstrap SKILL.md is still a stub"

    def test_control_plane_bootstrap_skill_has_five_databases(self) -> None:
        content = self._skill_content("control-plane-bootstrap")
        assert "Work Items" in content
        assert "Runs" in content
        assert "Approvals" in content
        assert "Activity Log" in content
        assert "Sources" in content

    def test_control_plane_bootstrap_skill_has_queue_row_fields(self) -> None:
        content = self._skill_content("control-plane-bootstrap")
        # All queue row fields from plan-14 must be present
        for field in ("Name", "Status", "Priority", "Owner", "Agent", "Source", "Output URL", "Retry Count"):
            assert field in content, f"Queue field '{field}' missing from control-plane-bootstrap skill"

    def test_control_plane_bootstrap_skill_has_workspace_verification(self) -> None:
        content = self._skill_content("control-plane-bootstrap")
        assert "workspace" in content.lower() or "Workspace" in content
        assert "verification" in content.lower() or "Verification" in content

    def test_control_plane_bootstrap_skill_has_anti_patterns(self) -> None:
        content = self._skill_content("control-plane-bootstrap")
        assert "source of truth" in content.lower()

    def test_context_audit_skill_not_stub(self) -> None:
        content = self._skill_content("context-audit")
        assert self._line_count(content) > 30, "context-audit SKILL.md is still a stub"

    def test_context_audit_skill_has_all_six_contract_fields(self) -> None:
        content = self._skill_content("context-audit")
        assert "Read First" in content
        assert "Read When Needed" in content
        assert "Do Not Load" in content
        assert "Tools And Skills" in content or "Tools and Skills" in content
        assert "Output Folder" in content
        assert "Done" in content

    def test_context_audit_skill_has_severity_ranking(self) -> None:
        content = self._skill_content("context-audit")
        assert "Critical" in content or "critical" in content
        assert "High" in content
        assert "Medium" in content

    def test_context_audit_skill_has_findings_output_format(self) -> None:
        content = self._skill_content("context-audit")
        assert "Findings" in content or "findings" in content


# ---------------------------------------------------------------------------
# 6. Brief template section completeness
# ---------------------------------------------------------------------------


class TestBriefTemplateCompleteness:
    """templates/customer/client-automation-brief.md must have all sections from plan-14."""

    def _template_content(self) -> str:
        from genomes_agentic_os.scaffold import template_source_dir
        path = template_source_dir() / "customer" / "client-automation-brief.md"
        assert path.is_file(), "client-automation-brief.md template is missing"
        return path.read_text(encoding="utf-8")

    def test_template_has_all_required_sections(self) -> None:
        content = self._template_content()
        required = [
            "## Outcome",
            "## Current Manual Workflow",
            "## Systems Involved",
            "## Inputs",
            "## Outputs",
            "## Frequency",
            "## Current Time Cost",
            "## Error Cost",
            "## Step Classification",
            "## Must Stay Manual",
            "## Automation Candidate Steps",
            "## Acceptance Criteria",
            "## Approval Gate",
            "## Rollback",
            "## Pilot Scope",
            "## Data Boundaries",
            "## Metrics Baseline",
        ]
        for section in required:
            assert section in content, f"Missing section '{section}' in client-automation-brief.md template"

    def test_template_has_layer_triage_table(self) -> None:
        """Template must contain the layer-triage classification table (plan-14 AC2)."""
        content = self._template_content()
        assert "Deterministic" in content
        assert "Rule-Based" in content or "Rule-based" in content
        assert "LLM-Needed" in content or "LLM-needed" in content
        assert "Human Judgment" in content or "Human judgment" in content

    def test_template_has_no_private_terms(self) -> None:
        """Template must contain no private Genome or course-specific identifiers."""
        from genomes_agentic_os.scaffold import template_source_dir
        import re
        content = (template_source_dir() / "customer" / "client-automation-brief.md").read_text(encoding="utf-8").lower()
        for term in PRIVATE_TERMS:
            match = re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", content)
            assert not match, f"Private term '{term}' found in client-automation-brief.md template"
