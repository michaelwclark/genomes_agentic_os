#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise AssertionError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}")
    return completed.stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate(repo: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-os-feature-01-") as tmp:
        runtime = Path(tmp) / "agentic_os"
        linked_repo = Path(tmp) / "linked_losmon"
        linked_repo.mkdir()
        run(["uv", "run", "agentic-os", "init", "--target", str(runtime)], repo)
        command = [
            "uv", "run", "agentic-os", "project", "create", "los", "losmon_replacement",
            "--root", str(runtime), "--repo", str(linked_repo), "--notion", "https://notion.example/project",
            "--jira", "FLYWL", "--lane", "engineering", "--status", "active",
        ]
        run(command, repo)
        project = runtime / "los" / "02-projects" / "losmon_replacement"
        for name in ("README.md", "project.yml", "status.md", "decisions.md", "source-map.md"):
            require((project / name).is_file(), f"missing project file: {name}")
        require((project / "artifacts").is_dir(), "missing artifacts directory")
        require("losmon_replacement" in (runtime / "los" / "00-control-plane" / "active-work.md").read_text(), "missing active-work row")
        require("losmon_replacement" in (runtime / "los" / "02-projects" / "README.md").read_text(), "missing project index row")
        source_map = (project / "source-map.md").read_text()
        require(str(linked_repo) in source_map, "missing repo source-map row")
        require("https://notion.example/project" in source_map, "missing Notion source-map row")
        require("FLYWL" in source_map, "missing Jira source-map row")
        status = project / "status.md"
        status.write_text("# local status edit\n", encoding="utf-8")
        run(command, repo)
        require(status.read_text(encoding="utf-8") == "# local status edit\n", "project create overwrote local status edit")
        run(["uv", "run", "agentic-os", "project", "create", "lenders", "lender_portal", "--root", str(runtime)], repo)
        require((runtime / "los" / "02-projects" / "lender_portal" / "project.yml").is_file(), "lenders alias did not route to los")
        require(not (runtime / "lenders").exists(), "lenders alias created an unexpected domain")
        run(["uv", "run", "agentic-os", "validate", "--root", str(runtime)], repo)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    try:
        validate(Path(args.repo).resolve())
    except AssertionError as exc:
        print(f"feature 01 holdout validation failed: {exc}", file=sys.stderr)
        return 1
    print("feature 01 holdout validation passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
