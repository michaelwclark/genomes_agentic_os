#!/usr/bin/env python3
"""Local holdout validation for feature 00.

This intentionally avoids Notion writes. It checks source artifacts and creates a
throwaway installed Agentic OS root to verify the plan backlog copy.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REQUIRED_FEATURE_FILES = (
    "feature.yml",
    "SPEC.md",
    "INVESTIGATION.md",
    "PLAN.md",
    "WORKLOG.md",
    "SUMMARY.md",
    "NEXT.md",
    "HOLDOUT_QA.md",
    "HOLDOUT_QA_RESULTS.md",
    "JUDGMENT.md",
    "MEMORY.md",
)

REQUIRED_RUNTIME_PLAN_FILES = (
    "README.md",
    "00-current-state-and-gap-map.md",
    "09-future-ideas-intake.md",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise AssertionError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}")


def validate(repo: Path) -> None:
    feature_dir = repo / "features" / "00-current-state-and-gap-map"
    require(feature_dir.is_dir(), "missing feature 00 audit folder")
    for filename in REQUIRED_FEATURE_FILES:
        require((feature_dir / filename).is_file(), f"missing feature 00 artifact: {filename}")

    plan = repo / "PLANS" / "00-current-state-and-gap-map.md"
    require(plan.is_file(), "missing source plan for feature 00")
    text = plan.read_text(encoding="utf-8")
    require("What Exists Now" in text, "feature 00 plan missing current-state section")
    require("What Is Not Built Yet" in text, "feature 00 plan missing gap section")

    run_state_path = repo / "RUN_STATE.json"
    require(run_state_path.is_file(), "missing RUN_STATE.json")
    run_state = json.loads(run_state_path.read_text(encoding="utf-8"))
    features = run_state.get("features", [])
    feature_00 = next((item for item in features if str(item.get("prefix")) == "00"), None)
    require(feature_00 is not None, "RUN_STATE.json does not include prefix 00")
    require(feature_00.get("state") == "done" or feature_00.get("status") == "done", "RUN_STATE prefix 00 is not done")

    with tempfile.TemporaryDirectory(prefix="agentic-os-feature-00-") as tmp:
        runtime_root = Path(tmp) / "agentic_os"
        run(["uv", "run", "agentic-os", "init", "--target", str(runtime_root)], cwd=repo)
        run(["uv", "run", "agentic-os", "validate", "--root", str(runtime_root)], cwd=repo)
        plans_dir = runtime_root / "shared_factory" / "05-knowledge" / "plans"
        for filename in REQUIRED_RUNTIME_PLAN_FILES:
            require((plans_dir / filename).is_file(), f"missing installed runtime plan artifact: {filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate feature 00 without live Notion writes.")
    parser.add_argument("--repo", default=".", help="Path to genomes_agentic_os repository root.")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    try:
        validate(repo)
    except AssertionError as exc:
        print(f"feature 00 holdout validation failed: {exc}", file=sys.stderr)
        return 1
    print("feature 00 holdout validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
