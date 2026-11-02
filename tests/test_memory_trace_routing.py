"""Run the real emitter with a sterile home and an inert curl substitute."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "harness/hooks/harness-emit-trace.sh"


@pytest.mark.parametrize("primary,legacy,expected", [
    (None, None, "http://127.0.0.1:3166/mcp"),
    (None, "http://legacy-fixture.invalid/mcp", "http://legacy-fixture.invalid/mcp"),
    ("http://brain-fixture.invalid/mcp", "http://legacy-fixture.invalid/mcp", "http://brain-fixture.invalid/mcp"),
    ("", "http://legacy-fixture.invalid/mcp", "http://legacy-fixture.invalid/mcp"),
])
def test_real_hook_default_override_precedence_and_rpc_without_network(tmp_path, primary, legacy, expected):
    jq = shutil.which("jq")
    assert jq, "hook qualification requires the configured jq executable"
    binary = tmp_path / "bin"; binary.mkdir()
    (binary / "jq").symlink_to(jq)
    capture = tmp_path / "request.json"
    curl = binary / "curl"
    curl.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
body = json.loads(args[args.index('-d')+1])
Path(args[args.index('-o')+1]).write_text('{}')
Path(os.environ['FIXTURE_CAPTURE']).write_text(json.dumps({'args': args, 'body': body}))
sys.stdout.write('200')
''')
    curl.chmod(0o700)
    home = tmp_path / "home"; home.mkdir()
    temporary = tmp_path / "temp"; temporary.mkdir()
    env = {"PATH": f"{binary}:/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(temporary),
           "FIXTURE_CAPTURE": str(capture)}
    if primary is not None: env["GENOMES_BRAIN_MCP_URL"] = primary
    if legacy is not None: env["LOSMON_MEMORY_MCP_URL"] = legacy
    result = subprocess.run(["/bin/bash", str(HOOK), "fixture"], input='{"session_id":"fixture-session","cwd":"fixture"}',
                            text=True, capture_output=True, env=env, timeout=5)
    assert result.returncode == 0
    assert result.stdout == '{"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":""}}\n'
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        try:
            request = json.loads(capture.read_text())
            log = (home / ".local/state/harness/emit-trace.log").read_text()
            if "async_status=200" in log: break
        except (FileNotFoundError, ValueError): pass
        time.sleep(0.01)
    else: pytest.fail("bounded inert hook dispatch did not complete")
    assert request["args"][request["args"].index("POST")+1] == expected
    assert request["body"]["method"] == "tools/call"
    assert request["body"]["params"]["name"] == "memory_write"
    arguments = request["body"]["params"]["arguments"]
    assert arguments["kindHint"] == "AGENT_TRACE" and "fixture-session" in arguments["content"]
    assert arguments["persona"].startswith("fixture-")
    assert not list(temporary.iterdir())
