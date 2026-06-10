"""Tests for customer-install strict alignment and schema shipping (U6).

Covers:
  (a) fresh root install contains harness/schemas/ with the expected JSON files
  (b) customer install passes validate --strict with zero findings
  (c) resolution order — a deliberately tightened schema placed in
      harness/schemas/ wins over the repo copy

Deliberately kept separate from tests/test_cli_scaffold.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.customer import customer_init
from genomes_agentic_os.scaffold import init_os, install_docs
from genomes_agentic_os.validate import SCHEMA_TARGETS, validate_schemas_strict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def harness(root: Path) -> Path:
    return root / "harness"


def _init_root(root: Path) -> None:
    """Create a minimal valid OS root via the CLI (mirrors test_validation_strictness.py)."""
    assert main(["init", "--target", str(root)]) == 0


def _write_customer_profile(path: Path) -> None:
    """Write the minimal customer profile used across tests."""
    profile: dict[str, Any] = {
        "customer": {
            "slug": "test_co",
            "display_name": "Test Co",
            "owner": "owner@test.co",
            "approved_domains": ["operations"],
        }
    }
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) Fresh root install contains harness/schemas/ with expected schema files
# ---------------------------------------------------------------------------


def test_init_root_installs_schemas_dir(tmp_path: Path) -> None:
    """init_os must create harness/schemas/ populated with the SCHEMA_TARGETS JSON files."""
    root = tmp_path / "os_root"
    _init_root(root)

    schemas_dir = harness(root) / "schemas"
    assert schemas_dir.is_dir(), "harness/schemas/ directory was not created by init_os"

    installed = {p.name for p in schemas_dir.glob("*.json")}
    # Every schema filename that appears as a SCHEMA_TARGETS key must be present.
    for schema_filename in SCHEMA_TARGETS:
        assert schema_filename in installed, (
            f"harness/schemas/{schema_filename} missing after init_os"
        )


def test_docs_update_installs_schemas_on_existing_root(tmp_path: Path) -> None:
    """docs update delivers harness/schemas/ to roots that predate the feature."""
    root = tmp_path / "os_root"
    _init_root(root)
    shutil.rmtree(harness(root) / "schemas")

    install_docs(root)

    installed = {p.name for p in (harness(root) / "schemas").glob("*.json")}
    for schema_filename in SCHEMA_TARGETS:
        assert schema_filename in installed, (
            f"harness/schemas/{schema_filename} missing after docs update"
        )


def test_customer_init_installs_schemas_dir(tmp_path: Path) -> None:
    """customer_init must create harness/schemas/ on the customer root."""
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_root"
    _write_customer_profile(profile)

    customer_init("test_co", profile, root)

    schemas_dir = harness(root) / "schemas"
    assert schemas_dir.is_dir(), "harness/schemas/ directory was not created by customer_init"

    installed = {p.name for p in schemas_dir.glob("*.json")}
    for schema_filename in SCHEMA_TARGETS:
        assert schema_filename in installed, (
            f"harness/schemas/{schema_filename} missing after customer_init"
        )


# ---------------------------------------------------------------------------
# (b) Customer install passes validate --strict with zero findings
# ---------------------------------------------------------------------------


def test_customer_install_strict_clean(tmp_path: Path) -> None:
    """customer_init must produce a root that passes validate_schemas_strict with zero findings."""
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_root"
    _write_customer_profile(profile)

    customer_init("test_co", profile, root)

    findings = validate_schemas_strict(root)
    assert findings == [], (
        "customer install has strict schema violations:\n"
        + "\n".join(f"  {f.schema}: {f.path.name}: {f.message}" for f in findings)
    )


def test_customer_validate_cli_exits_zero(tmp_path: Path) -> None:
    """agentic-os customer validate must exit 0 on a fresh customer install."""
    profile = tmp_path / "profile.yml"
    root = tmp_path / "customer_root"
    _write_customer_profile(profile)
    customer_init("test_co", profile, root)

    exit_code = main(["customer", "validate", "--root", str(root)])
    assert exit_code == 0, "customer validate exited non-zero for a fresh customer install"


# ---------------------------------------------------------------------------
# (c) Resolution order — install's harness/schemas/ wins over the repo copy
# ---------------------------------------------------------------------------


def test_resolution_order_install_schemas_take_precedence(tmp_path: Path) -> None:
    """A tightened schema placed in harness/schemas/ is used instead of the repo copy.

    We put a schema that makes every document invalid (by requiring a property
    that the real registries never have) into harness/schemas/, then confirm
    that strict validation now returns findings — proving the install-local
    schema was used rather than the repo copy.
    """
    root = tmp_path / "os_root"
    _init_root(root)

    # Verify baseline: strict is clean with the original schema.
    assert validate_schemas_strict(root) == []

    # Replace backup-policy.schema.json in harness/schemas/ with a schema that
    # demands a property ("__must_not_exist__") that no real backup-policy.yml
    # will ever contain.
    tightened_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["__must_not_exist__"],
    }
    install_schema_path = harness(root) / "schemas" / "backup-policy.schema.json"
    assert install_schema_path.is_file(), (
        "backup-policy.schema.json was not installed into harness/schemas/"
    )
    install_schema_path.write_text(json.dumps(tightened_schema), encoding="utf-8")

    # Now strict validation must produce at least one finding from the tightened schema.
    findings = validate_schemas_strict(root)
    backup_findings = [f for f in findings if "backup-policy" in f.schema]
    assert backup_findings, (
        "Expected findings from tightened harness/schemas/backup-policy.schema.json, got none — "
        "resolution order may not be preferring the install-local schema"
    )
