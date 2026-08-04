#!/usr/bin/env python3
"""Derive a guarded SemVer release candidate from Conventional Commits.

The program is intentionally read-only: it examines commits between a reachable
SemVer tag and one target SHA, emits a deterministic candidate, and never tags,
publishes, or changes a version file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass


SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CONVENTIONAL_SUBJECT = re.compile(
    r"^(?P<kind>[a-z]+)(?:\([^\r\n)]*\))?(?P<breaking>!)?:"
)
RELEASE_LEVELS = {"patch": 1, "minor": 2, "major": 3}


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "Version":
        match = SEMVER.fullmatch(value.removeprefix("v"))
        if match is None:
            raise ValueError(f"not a stable SemVer value: {value}")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def change_level(commits: list[str]) -> str | None:
    """Return the highest release level represented by Conventional Commits."""
    level: str | None = None
    for commit in commits:
        subject = commit.splitlines()[0] if commit.splitlines() else ""
        match = CONVENTIONAL_SUBJECT.match(subject)
        breaking = "BREAKING CHANGE:" in commit or (
            match is not None and match.group("breaking") == "!"
        )
        if breaking:
            candidate = "major"
        elif match is not None and match.group("kind") == "feat":
            candidate = "minor"
        elif match is not None and match.group("kind") in {"fix", "perf"}:
            candidate = "patch"
        else:
            continue
        if level is None or RELEASE_LEVELS[candidate] > RELEASE_LEVELS[level]:
            level = candidate
    return level


def next_version(base: Version, level: str | None, *, major_version_zero: bool) -> Version | None:
    if level is None:
        return None
    if level == "major":
        if major_version_zero and base.major == 0:
            return Version(base.major, base.minor + 1, 0)
        return Version(base.major + 1, 0, 0)
    if level == "minor":
        return Version(base.major, base.minor + 1, 0)
    if level == "patch":
        return Version(base.major, base.minor, base.patch + 1)
    raise ValueError(f"unsupported release level: {level}")


def _commits(base_tag: str, target_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%B%x00", f"{base_tag}..{target_sha}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [commit.strip() for commit in result.stdout.split("\x00") if commit.strip()]


def _write_github_output(values: dict[str, str]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-tag", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("--major-version-zero", action="store_true")
    arguments = parser.parse_args()

    base = Version.parse(arguments.base_tag)
    commits = _commits(arguments.base_tag, arguments.target_sha)
    level = change_level(commits)
    candidate = next_version(base, level, major_version_zero=arguments.major_version_zero)
    version = str(candidate) if candidate is not None else ""
    if arguments.expected_version and version != arguments.expected_version:
        raise SystemExit(
            "derived release candidate does not match the project version: "
            f"expected {arguments.expected_version}, derived {version or 'none'}"
        )

    values = {
        "base_tag": arguments.base_tag,
        "target_sha": arguments.target_sha,
        "release_level": level or "none",
        "version": version,
        "release_required": str(candidate is not None).lower(),
    }
    _write_github_output(values)
    print(json.dumps(values, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
