"""Instance compatibility: operator-chosen domain names are pure data.

Existing installs were created when the product shipped personal default
domain names. After de-personalization (AGE-34), any installed OS —
whatever its domains are called — must keep validating and must update
additively: `update apply` and `doctor`-style repair must never plant
the built-in default domains next to an operator's own set.
"""

from __future__ import annotations

from pathlib import Path

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import validate_root


# Root-level discovery adapters scaffolded next to the domain directories so
# Claude and Codex pick up the harness contract when a conversation starts at
# the installed root. They are instruction surface, not domains.
ROOT_ADAPTERS = {"AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"}
INSTALL_ROOTS = {"domains", "harness", "lib"}


def _top_level(root: Path) -> set[str]:
    return {
        path.name
        for path in root.iterdir()
        if not path.name.startswith(".") and path.name not in ROOT_ADAPTERS
    }


def test_arbitrary_domain_names_validate_and_update_additively(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"

    # Scaffold with operator-chosen names instead of the built-in defaults.
    assert main(["init", "--target", str(root), "--domains", "alpha_client,beta_ops"]) == 0
    assert _top_level(root) == INSTALL_ROOTS
    assert {path.name for path in (root / "domains").iterdir() if path.is_dir()} == {"alpha_client", "beta_ops"}
    assert validate_root(root).ok
    assert main(["validate", "--root", str(root)]) == 0

    # Adding one more arbitrary domain stays additive: no default domains
    # appear alongside the operator's set.
    assert main(["domain", "create", "gamma_labs", "--root", str(root)]) == 0
    assert _top_level(root) == INSTALL_ROOTS
    assert {path.name for path in (root / "domains").iterdir() if path.is_dir()} == {
        "alpha_client",
        "beta_ops",
        "gamma_labs",
    }

    # The additive update path succeeds and leaves the domain set alone.
    assert main(["update", "plan", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["update", "apply", "--root", str(root)]) == 0
    capsys.readouterr()
    assert _top_level(root) == INSTALL_ROOTS
    assert {path.name for path in (root / "domains").iterdir() if path.is_dir()} == {
        "alpha_client",
        "beta_ops",
        "gamma_labs",
    }
    assert validate_root(root).ok


def test_legacy_personal_domain_names_keep_working_as_data(tmp_path: Path, capsys) -> None:
    """A tree that still uses legacy personal domain names is just data.

    This simulates an existing personal install: the names carry no
    special meaning to the product anymore, and validate/update treat
    them exactly like any other operator-chosen domain names.
    """
    root = tmp_path / "agentic_os"

    assert main(["init", "--target", str(root), "--domains", "personal,clarks_consulting,los,archive"]) == 0
    assert _top_level(root) == INSTALL_ROOTS
    assert {path.name for path in (root / "domains").iterdir() if path.is_dir()} == {
        "personal",
        "clarks_consulting",
        "los",
        "archive",
    }
    assert validate_root(root).ok

    assert main(["update", "plan", "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["update", "apply", "--root", str(root)]) == 0
    capsys.readouterr()

    # Update stayed additive: the legacy names survive and the neutral
    # defaults were NOT planted next to them.
    assert _top_level(root) == INSTALL_ROOTS
    assert {path.name for path in (root / "domains").iterdir() if path.is_dir()} == {
        "personal",
        "clarks_consulting",
        "los",
        "archive",
    }
    assert validate_root(root).ok
