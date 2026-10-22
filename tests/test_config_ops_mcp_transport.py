"""Transport safety at the real TOML merge and install boundary."""
from __future__ import annotations

import pytest

from genomes_agentic_os import config_ops as c

tomllib = pytest.importorskip("tomllib")

STDIO = '[mcp_servers.genomes_brain]\ncommand = "ssh"\nargs = ["host", "native-stdio"]\n'
HTTP = '[mcp_servers.genomes_brain]\nurl = "https://brain.invalid/mcp"\n'


@pytest.mark.parametrize("existing, proposed", [(STDIO, HTTP), (HTTP, STDIO)])
def test_competing_transport_preserved_without_secret_values(existing, proposed):
    result, conflicts = c.merge_config(existing, proposed)
    assert result == existing
    assert len(conflicts) == 1
    assert "incompatible MCP transport" in conflicts[0]
    assert "host" not in conflicts[0] and "brain.invalid" not in conflicts[0]
    assert tomllib.loads(result) == tomllib.loads(existing)


@pytest.mark.parametrize("existing", [STDIO, HTTP])
def test_conflicted_server_does_not_block_unrelated_settings(existing):
    proposed = (HTTP if existing == STDIO else STDIO) + '\n[features]\nweb_search = true\n'
    result, conflicts = c.merge_config(existing, proposed)
    parsed = tomllib.loads(result)
    assert parsed["mcp_servers"] == tomllib.loads(existing)["mcp_servers"]
    assert parsed["features"]["web_search"] is True
    assert len(conflicts) == 1


@pytest.mark.parametrize("nested_first", [False, True])
def test_incompatible_server_subtables_preserved_regardless_of_order(nested_first):
    child = '[mcp_servers.genomes_brain.env]\nNEW_VALUE = "managed"\n'
    proposed = child + HTTP if nested_first else HTTP + child
    result, conflicts = c.merge_config(STDIO, proposed)
    assert result == STDIO
    assert len(conflicts) == 1


@pytest.mark.parametrize("existing", [STDIO, HTTP])
def test_same_transport_common_additions_and_repeat_install(existing):
    proposed = existing + 'startup_timeout_sec = 20\n'
    result, conflicts = c.merge_config(existing, proposed)
    assert not conflicts
    assert tomllib.loads(result)["mcp_servers"]["genomes_brain"]["startup_timeout_sec"] == 20
    repeated, repeated_conflicts = c.merge_config(result, proposed)
    assert repeated == result and not repeated_conflicts


def test_custom_http_url_kept_with_existing_conflict_semantics():
    proposed = HTTP.replace("brain.invalid", "managed.invalid") + 'startup_timeout_sec = 20\n'
    result, conflicts = c.merge_config(HTTP, proposed)
    assert tomllib.loads(result)["mcp_servers"]["genomes_brain"]["url"] == "https://brain.invalid/mcp"
    assert len(conflicts) == 1


@pytest.mark.parametrize("existing", ["", "\n\n", '[features]\nweb_search = true\n'])
@pytest.mark.parametrize("server", [STDIO, HTTP])
def test_new_coherent_server_supported(existing, server):
    result, conflicts = c.merge_config(existing, server)
    assert not conflicts
    assert tomllib.loads(result)["mcp_servers"] == tomllib.loads(server)["mcp_servers"]
    if not existing.strip():
        assert result == server


@pytest.mark.parametrize("existing", ["", STDIO, HTTP])
@pytest.mark.parametrize("bad", [
    STDIO + 'url = "https://other.invalid/mcp"\n',
    HTTP + 'args = ["host"]\n',
    '[mcp_servers.genomes_brain]\nargs = ["host"]\n',
    STDIO + STDIO,
    STDIO + '[mcp_servers."genomes_brain"]\ncommand = "ssh"\n',
    STDIO + 'command = "other"\n',
])
def test_invalid_managed_template_refused_even_for_first_install(existing, bad):
    with pytest.raises(ValueError, match="MCP"):
        c.merge_config(existing, bad)


@pytest.mark.parametrize("bad", [
    STDIO + 'url = "https://other.invalid/mcp"\n',
    '[mcp_servers.genomes_brain]\nargs = ["host"]\n',
    STDIO + 'command = "other"\n',
    STDIO + STDIO,
])
def test_ambiguous_existing_transport_is_not_extended(bad):
    result, conflicts = c.merge_config(bad, HTTP)
    assert result == bad
    assert len(conflicts) == 1


@pytest.mark.parametrize("header", ['mcp_servers."genomes_brain"', "mcp_servers.'genomes_brain'"])
def test_quoted_alias_is_preserved_instead_of_duplicate_table(header):
    existing = STDIO.replace("mcp_servers.genomes_brain", header)
    result, conflicts = c.merge_config(existing, HTTP)
    assert result == existing
    assert len(conflicts) == 1
    assert tomllib.loads(result)["mcp_servers"]["genomes_brain"]["command"] == "ssh"


def test_environment_values_are_not_treated_as_server_transports():
    existing = STDIO + '[mcp_servers.genomes_brain.env]\ncommand = "value"\n'
    proposed = STDIO + '[mcp_servers.genomes_brain.env]\nurl = "value"\n'
    result, conflicts = c.merge_config(existing, proposed)
    assert not conflicts
    assert tomllib.loads(result)["mcp_servers"]["genomes_brain"]["env"] == {
        "command": "value", "url": "value",
    }


@pytest.mark.parametrize("header", [
    'mcp_servers."genomes_\\u0062rain"',
    'mcp_servers.genomes_brain] # existing comment',
    'mcp_servers . genomes_brain ',
])
def test_equivalent_custom_header_is_not_shadowed(header):
    existing = STDIO.replace("mcp_servers.genomes_brain", header)
    if "# existing comment" in header:
        existing = existing.replace("comment]", "comment")
    result, conflicts = c.merge_config(existing, HTTP)
    assert result == existing
    assert len(conflicts) == 1
    assert tomllib.loads(result)["mcp_servers"]["genomes_brain"]["command"] == "ssh"


@pytest.mark.parametrize("header", ['mcp_servers."brain"', 'mcp_servers.brain ', "mcp_servers.'brain'"])
def test_unhandled_managed_header_spelling_is_refused(header):
    with pytest.raises(ValueError, match="MCP server table spelling"):
        c.merge_config("", HTTP.replace("mcp_servers.genomes_brain", header))


@pytest.mark.parametrize("name", ['""', "''"])
def test_empty_quoted_server_does_not_bypass_transport_guard(name):
    managed = (STDIO + 'url = "https://brain.invalid/mcp"\n').replace("genomes_brain", name)
    with pytest.raises(ValueError, match="MCP"):
        c.merge_config("", managed)


def test_unsupported_quoted_name_refuses_before_merge():
    unsupported = STDIO.replace("genomes_brain", '"genomes_\\U00000062rain"')
    with pytest.raises(ValueError, match="Unsupported quoted MCP"):
        c.merge_config(unsupported, HTTP)


@pytest.mark.parametrize("confirm", [False, True])
def test_real_generated_install_does_not_corrupt_existing_stdio(tmp_path, confirm):
    config = tmp_path / "config.toml"
    config.write_text(STDIO)
    before = config.read_bytes()
    generated = c.config_template("agentic_os_root", tmp_path)
    assert "url" in tomllib.loads(generated)["mcp_servers"]["genomes_brain"]
    preview = c.install_config(tmp_path, layer="agentic_os_root", dry_run=True)
    assert preview.conflicts and config.read_bytes() == before
    applied = c.install_config(tmp_path, layer="agentic_os_root", dry_run=False, confirm_conflicts=confirm)
    assert applied.blocked is (not confirm)
    parsed = tomllib.loads(config.read_text())["mcp_servers"]["genomes_brain"]
    assert parsed == tomllib.loads(STDIO)["mcp_servers"]["genomes_brain"]
    if not confirm:
        assert config.read_bytes() == before
        assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml"]
    repeated = c.install_config(tmp_path, layer="agentic_os_root", dry_run=False, confirm_conflicts=confirm)
    assert repeated.conflicts
    assert tomllib.loads(config.read_text())["mcp_servers"]["genomes_brain"] == parsed


def test_new_generated_install_is_repeatable(tmp_path):
    first = c.install_config(tmp_path, layer="agentic_os_root", dry_run=False)
    assert not first.blocked
    initial = (tmp_path / "config.toml").read_bytes()
    second = c.install_config(tmp_path, layer="agentic_os_root", dry_run=False)
    assert not second.blocked
    assert (tmp_path / "config.toml").read_bytes() == initial


@pytest.mark.parametrize("existing", [
    '[mcp_servers]\ngenomes_brain={command="ssh",args=["host"]}\n',
    'mcp_servers.genomes_brain.command="ssh"\n',
    'mcp_servers={genomes_brain={command="ssh"}}\n',
    '["mcp_servers".genomes_brain]\ncommand="ssh"\n',
    "['mcp_servers'.genomes_brain]\ncommand='ssh'\n",
    '[mcp_servers.genomes_brain]\n"command"="ssh"\n',
    "[mcp_servers.genomes_brain]\n'url'='https://custom.invalid/mcp'\n",
])
def test_valid_unhandled_mcp_layout_preserved_with_unrelated_additions(existing):
    original = tomllib.loads(existing)
    result, conflicts = c.merge_config(existing, HTTP + '[features]\nweb_search=true\n')
    assert len(conflicts) == 1
    parsed = tomllib.loads(result)
    assert parsed["mcp_servers"] == original["mcp_servers"]
    assert parsed["features"]["web_search"] is True
    assert "ssh" not in conflicts[0] and "custom.invalid" not in conflicts[0]
    repeated, repeated_conflicts = c.merge_config(result, HTTP + '[features]\nweb_search=true\n')
    assert repeated == result and repeated_conflicts == conflicts


@pytest.mark.parametrize("managed", [
    '[mcp_servers]\ngenomes_brain={command="ssh"}\n',
    'mcp_servers.genomes_brain.command="ssh"\n',
    '[mcp_servers.genomes_brain]\n"command"="ssh"\nurl="https://brain.invalid/mcp"\n',
    '[mcp_servers.genomes_brain]\nargs=[\n"host",\n]\ncommand="ssh"\n',
])
@pytest.mark.parametrize("existing", ["", STDIO])
def test_unsupported_managed_definition_refused_before_any_merge(existing, managed):
    tomllib.loads(managed)
    with pytest.raises(ValueError, match="Unsupported managed MCP definition layout"):
        c.merge_config(existing, managed)


def test_server_array_layout_is_preserved_without_reopening_a_table():
    existing = '[[mcp_servers.genomes_brain]]\ncommand="ssh"\n'
    result, conflicts = c.merge_config(existing, HTTP)
    assert result == existing and len(conflicts) == 1


def test_quoted_environment_keys_do_not_block_coherent_transport_additions():
    existing = STDIO + '[mcp_servers.genomes_brain.env]\n"command"="value"\n'
    result, conflicts = c.merge_config(existing, STDIO + 'startup_timeout_sec=20\n')
    assert not conflicts
    parsed = tomllib.loads(result)["mcp_servers"]["genomes_brain"]
    assert parsed["command"] == "ssh" and parsed["startup_timeout_sec"] == 20
    assert parsed["env"]["command"] == "value"
