"""Tests for genomes_agentic_os.mcp_catalog: the layer-aware MCP server
catalog, domain gating via harness/registries/mcp-domain-gating.yml, and the
rendered markdown table used in generated docs and TOOLS.md.

These exercise the module's real public behavior post-de-personalization:
CORE/DOMAIN_GATED/VISIBLE_ONLY server partitioning, registry loading (missing
root, missing file, malformed YAML, malformed entries, unknown server ids),
domain-name normalization, and the public_customer redaction path.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from genomes_agentic_os.mcp_catalog import (
    CORE_MCP_IDS,
    DOMAIN_GATED_MCP_IDS,
    DOMAIN_GATING_REGISTRY,
    MCP_SERVERS,
    VISIBLE_ONLY_MCP_IDS,
    active_domain_ids,
    all_visible_mcp_ids,
    config_mcp_ids,
    load_domain_mcp_gating,
    mcp_config_payload,
    mcp_status,
    mcp_tools_markdown,
)


def _make_os_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    root.mkdir()
    (root / ".agentic_root").write_text("", encoding="utf-8")
    return root


def _write_gating(root: Path, domains: dict) -> Path:
    registry = root / DOMAIN_GATING_REGISTRY
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(yaml.safe_dump({"domains": domains}), encoding="utf-8")
    return registry


# ---------------------------------------------------------------------------
# Catalog shape
# ---------------------------------------------------------------------------


def test_core_gated_and_visible_ids_partition_all_servers():
    all_ids = set(CORE_MCP_IDS) | set(DOMAIN_GATED_MCP_IDS) | set(VISIBLE_ONLY_MCP_IDS)
    assert all_ids == set(MCP_SERVERS)


def test_core_gated_and_visible_ids_are_disjoint():
    assert set(CORE_MCP_IDS).isdisjoint(DOMAIN_GATED_MCP_IDS)
    assert set(CORE_MCP_IDS).isdisjoint(VISIBLE_ONLY_MCP_IDS)
    assert set(DOMAIN_GATED_MCP_IDS).isdisjoint(VISIBLE_ONLY_MCP_IDS)


def test_all_visible_mcp_ids_is_deduplicated_union_of_every_server():
    ids = all_visible_mcp_ids()
    assert len(ids) == len(set(ids))
    assert set(ids) == set(MCP_SERVERS)


def test_mcp_config_payload_url_server_has_no_command_fields():
    payload = mcp_config_payload(MCP_SERVERS["notion"])
    assert payload["url"] == MCP_SERVERS["notion"].url
    assert "command" not in payload
    assert "args" not in payload
    assert payload["secret_policy"] == "no inline secrets; env var names only"


def test_mcp_config_payload_command_server_has_args_not_url():
    payload = mcp_config_payload(MCP_SERVERS["playwright"])
    assert payload["command"] == "npx"
    assert payload["args"] == ["@playwright/mcp@latest"]
    assert "url" not in payload


def test_mcp_config_payload_bearer_token_env_var_included_when_present():
    payload = mcp_config_payload(MCP_SERVERS["github"])
    assert payload["bearer_token_env_var"] == "GITHUB_PAT_TOKEN"


# ---------------------------------------------------------------------------
# load_domain_mcp_gating: registry loading + error paths
# ---------------------------------------------------------------------------


def test_load_domain_mcp_gating_no_path_returns_empty():
    assert load_domain_mcp_gating(None) == {}


def test_load_domain_mcp_gating_no_os_root_returns_empty(tmp_path):
    stray = tmp_path / "not_an_os_root" / "some" / "dir"
    stray.mkdir(parents=True)
    assert load_domain_mcp_gating(stray) == {}


def test_load_domain_mcp_gating_missing_registry_file_returns_empty(tmp_path):
    root = _make_os_root(tmp_path)
    assert load_domain_mcp_gating(root) == {}


def test_load_domain_mcp_gating_malformed_yaml_returns_empty(tmp_path):
    root = _make_os_root(tmp_path)
    registry = root / DOMAIN_GATING_REGISTRY
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("domains: [this is not: valid: yaml: at all", encoding="utf-8")
    assert load_domain_mcp_gating(root) == {}


def test_load_domain_mcp_gating_domains_key_not_a_dict_returns_empty(tmp_path):
    root = _make_os_root(tmp_path)
    registry = root / DOMAIN_GATING_REGISTRY
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(yaml.safe_dump({"domains": ["not", "a", "dict"]}), encoding="utf-8")
    assert load_domain_mcp_gating(root) == {}


def test_load_domain_mcp_gating_server_ids_not_a_list_skips_domain(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"alpha_ops": "sentry"})  # string, not a list/tuple
    assert load_domain_mcp_gating(root) == {}


def test_load_domain_mcp_gating_unknown_server_ids_are_dropped(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"alpha_ops": ["sentry", "made_up_server"]})
    gating = load_domain_mcp_gating(root)
    assert gating == {"alpha_ops": ("sentry",)}


def test_load_domain_mcp_gating_all_unknown_ids_drops_domain_entirely(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"alpha_ops": ["made_up_server"]})
    assert load_domain_mcp_gating(root) == {}


def test_load_domain_mcp_gating_normalizes_domain_name_casing_and_hyphens(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"Alpha-Ops": ["sentry"]})
    gating = load_domain_mcp_gating(root)
    assert gating == {"alpha_ops": ("sentry",)}


def test_load_domain_mcp_gating_walks_up_from_nested_path(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"alpha_ops": ["datadog"]})
    nested = root / "alpha_ops" / "02-projects" / "some_project"
    nested.mkdir(parents=True)
    assert load_domain_mcp_gating(nested) == {"alpha_ops": ("datadog",)}


# ---------------------------------------------------------------------------
# active_domain_ids
# ---------------------------------------------------------------------------


def test_active_domain_ids_from_path_parts(tmp_path):
    root = _make_os_root(tmp_path)
    target = root / "alpha_ops" / "02-projects" / "widgets"
    target.mkdir(parents=True)
    assert "alpha_ops" in active_domain_ids(target)


def test_active_domain_ids_from_explicit_approved_domains():
    domains = active_domain_ids(None, approved_domains=["Beta-Ops"])
    assert domains == {"beta_ops"}


def test_active_domain_ids_combines_path_and_approved(tmp_path):
    root = _make_os_root(tmp_path)
    target = root / "alpha_ops"
    target.mkdir()
    domains = active_domain_ids(target, approved_domains=["beta_ops"])
    assert "alpha_ops" in domains
    assert "beta_ops" in domains


# ---------------------------------------------------------------------------
# config_mcp_ids: gating on/off for a resolved config.toml server list
# ---------------------------------------------------------------------------


def test_config_mcp_ids_core_only_when_no_gating_registry(tmp_path):
    root = _make_os_root(tmp_path)
    ids = config_mcp_ids("domain_or_lane", root)
    assert set(ids) == set(CORE_MCP_IDS)


def test_config_mcp_ids_includes_gated_server_when_domain_active(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"alpha_ops": ["sentry"]})
    target = root / "alpha_ops"
    target.mkdir()
    ids = config_mcp_ids("domain_or_lane", target)
    assert "sentry" in ids
    assert set(CORE_MCP_IDS) <= set(ids)


def test_config_mcp_ids_excludes_gated_server_for_inactive_domain(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"alpha_ops": ["sentry"]})
    other = root / "beta_ops"
    other.mkdir()
    ids = config_mcp_ids("domain_or_lane", other)
    assert "sentry" not in ids


def test_config_mcp_ids_deduplicates_ids():
    ids = config_mcp_ids("domain_or_lane", None, gating={})
    assert len(ids) == len(set(ids))


def test_config_mcp_ids_explicit_gating_override_still_requires_active_domain(tmp_path):
    root = _make_os_root(tmp_path)
    # No registry file on disk; gating is supplied directly instead.
    ids_inactive = config_mcp_ids("domain_or_lane", root, gating={"alpha_ops": ("datadog",)})
    assert "datadog" not in ids_inactive

    nested = root / "alpha_ops"
    nested.mkdir()
    ids_active = config_mcp_ids("domain_or_lane", nested, gating={"alpha_ops": ("datadog",)})
    assert "datadog" in ids_active


# ---------------------------------------------------------------------------
# mcp_status
# ---------------------------------------------------------------------------


def test_mcp_status_core_server_is_installed_everywhere():
    assert mcp_status("notion", set()) == "installed at every layer"


def test_mcp_status_gated_server_active():
    status = mcp_status("sentry", {"alpha_ops"}, {"alpha_ops": ("sentry",)})
    assert status == "installed here"


def test_mcp_status_gated_server_inactive():
    status = mcp_status("sentry", {"beta_ops"}, {"alpha_ops": ("sentry",)})
    assert status == "visible; domain-gated via mcp-domain-gating registry"


def test_mcp_status_playwright_special_case():
    assert mcp_status("playwright", set(), {}) == "visible; opt in for browser automation layers"


def test_mcp_status_composio_default_message():
    assert mcp_status("composio", set(), {}) == "visible; endpoint or bridge approval required"


# ---------------------------------------------------------------------------
# mcp_tools_markdown: rendered table + gating visibility + public_customer gate
# ---------------------------------------------------------------------------


def test_mcp_tools_markdown_includes_all_visible_servers_by_default(tmp_path):
    root = _make_os_root(tmp_path)
    markdown = mcp_tools_markdown(root)
    for server_id in all_visible_mcp_ids():
        assert f"`{server_id}`" in markdown


def test_mcp_tools_markdown_include_inactive_false_hides_gated_and_visible_only(tmp_path):
    root = _make_os_root(tmp_path)
    markdown = mcp_tools_markdown(root, include_inactive=False)
    for server_id in CORE_MCP_IDS:
        assert f"`{server_id}`" in markdown
    for server_id in DOMAIN_GATED_MCP_IDS:
        assert f"`{server_id}`" not in markdown
    for server_id in VISIBLE_ONLY_MCP_IDS:
        assert f"`{server_id}`" not in markdown


def test_mcp_tools_markdown_include_inactive_false_still_shows_active_gated_server(tmp_path):
    root = _make_os_root(tmp_path)
    _write_gating(root, {"alpha_ops": ["sentry"]})
    target = root / "alpha_ops"
    target.mkdir()
    markdown = mcp_tools_markdown(target, include_inactive=False)
    assert "`sentry`" in markdown
    assert "`datadog`" not in markdown


def test_mcp_tools_markdown_public_customer_redacts_notion_and_renames_memory(tmp_path):
    root = _make_os_root(tmp_path)
    markdown = mcp_tools_markdown(root, public_customer=True)
    assert "Agentic memory" in markdown
    assert "Genome's Brain" not in markdown
    assert "customer workspace" in markdown.lower()


def test_mcp_tools_markdown_non_public_customer_keeps_internal_wording(tmp_path):
    root = _make_os_root(tmp_path)
    markdown = mcp_tools_markdown(root, public_customer=False)
    assert "Genome's Brain" in markdown
