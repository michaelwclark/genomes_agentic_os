#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], cwd: Path, expect: int = 0) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode != expect:
        raise AssertionError(f"command returned {completed.returncode}, expected {expect}: {' '.join(command)}\n{completed.stdout}")
    return completed.stdout


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}\n{text}")


def validate(repo: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-os-feature-02-") as tmp:
        runtime = Path(tmp) / "agentic_os"
        linked_repo = Path(tmp) / "linked_losmon"
        linked_repo.mkdir()
        run(["uv", "run", "agentic-os", "init", "--target", str(runtime)], repo)
        run(["uv", "run", "agentic-os", "project", "create", "los", "losmon_replacement", "--root", str(runtime), "--repo", str(linked_repo), "--lane", "engineering"], repo)
        routed = run(["uv", "run", "agentic-os", "route", "Deploy losmon_replacement to production", "--root", str(runtime)], repo)
        require(routed, "domain: los", "route domain")
        require(routed, "object_type: project", "route object type")
        require(routed, "production change", "approval risk")
        require(routed, "source-map.md", "source-map source")
        context = run(["uv", "run", "agentic-os", "context", "build", "--domain", "los", "--project", "losmon_replacement", "--root", str(runtime)], repo)
        require(context, "ROUTER.md", "root/domain router source")
        require(context, "project.yml", "project config source")
        here = run(["uv", "run", "--project", str(repo), "agentic-os", "here", "context", "build", "--root", str(runtime)], linked_repo)
        require(here, "losmon_replacement", "linked repo project detection")
        run(["uv", "run", "agentic-os", "route", "Do the thing", "--root", str(runtime)], repo, expect=2)
        run(["uv", "run", "agentic-os", "validate", "--root", str(runtime)], repo)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    try:
        validate(Path(args.repo).resolve())
    except AssertionError as exc:
        print(f"feature 02 holdout validation failed: {exc}", file=sys.stderr)
        return 1
    print("feature 02 holdout validation passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
