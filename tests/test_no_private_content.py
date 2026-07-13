"""Ratchet: the generic installer must not ship personal/private content.

Scans tracked files (git ls-files) in the shipped product surfaces for
private identifiers — personal client names, hostnames, account handles,
and the word-boundary domain slug ``los``. Modeled on the PRIVATE_TERMS
guard in src/genomes_agentic_os/customer.py, which protects generated
customer files; this test protects the source package itself.

Scope (AGE-34): src/, config/, templates/, schemas/, examples/ in full,
plus harness/registries/ and harness/bin/. The remaining harness
subtrees (skills/, commands/, hooks/, mcp/, rules/, plugins/,
libraries/, shared_factory/) carry doc-prose mentions that are tracked
as a follow-up sweep under AGE-38 and are intentionally NOT scanned yet.
Tightening this scope is the ratchet: extend SCAN_PREFIXES, never shrink
it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Substring terms (case-insensitive). "los" is separate because it needs a
# word boundary — plain substring would false-positive on "close", "logs",
# "philosophy", etc.
PRIVATE_SUBSTRING_TERMS = (
    "clarks_consulting",
    "momba",
    "genomesbox",
    "michaelwclark",
    "venturesgo",
    "kanga",
    "cashtree",
    "flywl",
    "banesco",
    "ledgerline",
    "losmon",
)

# Word-boundary terms, matched like customer.py's has_private_marker():
# (?<![a-z0-9_])term(?![a-z0-9_]) against the lowercased content.
PRIVATE_WORD_TERMS = ("los",)

# Directories that make up the shipped product surface under scan tonight.
SCAN_PREFIXES = (
    "src/",
    "config/",
    "templates/",
    "schemas/",
    "examples/",
    "harness/registries/",
    "harness/bin/",
)

# Legitimate uses of the terms above. Keep this list near-empty; every
# entry needs a reason.
ALLOWLIST = {
    # The PRIVATE_TERMS guard itself: it must name the private identifiers
    # in order to block them from generated customer-facing files.
    "src/genomes_agentic_os/customer.py",
}

_WORD_PATTERNS = {
    term: re.compile(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])")
    for term in PRIVATE_WORD_TERMS
}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", *SCAN_PREFIXES],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _scan_file(relative_path: str) -> list[str]:
    path = REPO_ROOT / relative_path
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # binary or unreadable assets carry no greppable text
    lowered_lines = content.lower().splitlines()
    offenders: list[str] = []
    for line_number, line in enumerate(lowered_lines, 1):
        for term in PRIVATE_SUBSTRING_TERMS:
            if term in line:
                offenders.append(f"{relative_path}:{line_number}: {term}")
        for term, pattern in _WORD_PATTERNS.items():
            if pattern.search(line):
                offenders.append(f"{relative_path}:{line_number}: \\b{term}\\b")
    return offenders


def test_shipped_surfaces_contain_no_private_terms() -> None:
    offenders: list[str] = []
    for relative_path in _tracked_files():
        if relative_path in ALLOWLIST:
            continue
        offenders.extend(_scan_file(relative_path))
    assert not offenders, (
        "Private terms found in shipped product surfaces "
        f"({len(offenders)} hits):\n" + "\n".join(sorted(offenders))
    )


def test_allowlist_entries_are_still_tracked_and_still_needed() -> None:
    """An allowlist entry that stops matching (or stops existing) is stale."""
    tracked = set(_tracked_files())
    for relative_path in sorted(ALLOWLIST):
        assert relative_path in tracked, f"allowlisted file no longer tracked: {relative_path}"
        assert _scan_file(relative_path), (
            f"allowlisted file no longer contains any private term; remove it "
            f"from ALLOWLIST: {relative_path}"
        )
