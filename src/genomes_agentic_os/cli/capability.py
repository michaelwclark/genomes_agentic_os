"""CLI commands that inspect installed OS capabilities."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..capability_registry import REGISTRY_FILES, inventory_markdown, load_registry, registry_payloads

from ._shared import DEFAULT_ROOT


def _installed_registry_payloads(root: Path) -> dict[str, dict[str, Any]]:
    """Merge readable installed registries with current built-in capabilities."""

    payloads = registry_payloads()
    for registry_name, relative_path in REGISTRY_FILES.items():
        registry_path = root / relative_path
        if registry_path.is_file():
            built_in = payloads.get(registry_name, {}).get(registry_name) or []
            installed = load_registry(registry_path, registry_name)
            merged: list[dict[str, Any]] = []
            positions: dict[str, int] = {}
            for entry in [*built_in, *installed]:
                identity = str(entry.get("id") or "").strip()
                if identity and identity in positions:
                    merged[positions[identity]] = entry
                else:
                    if identity:
                        positions[identity] = len(merged)
                    merged.append(entry)
            payloads[registry_name] = {registry_name: merged}
    return payloads


def handle_capability_list(args: argparse.Namespace) -> int:
    """List capabilities from installed registry files, optionally filtered by type."""
    root = Path(args.root).expanduser()
    cap_type = getattr(args, "type", None)
    payloads = registry_payloads()
    if cap_type:
        if cap_type not in payloads:
            print(f"Unknown capability type '{cap_type}'. Known types: {', '.join(sorted(payloads))}")
            return 1
        types_to_show = {cap_type: payloads[cap_type]}
    else:
        types_to_show = payloads
    for name, payload in types_to_show.items():
        collection_key = next(iter(payload))
        entries = payload[collection_key]
        print(f"\n## {name} ({len(entries)})")
        for entry in entries:
            entry_id = entry.get("id") or entry.get("command") or "(unknown)"
            description = entry.get("description", "")
            print(f"  {entry_id}" + (f" — {description}" if description else ""))
    installed_path = root / REGISTRY_FILES.get("capabilities", "harness/registries/capabilities.yml")
    if installed_path.exists():
        installed = load_registry(installed_path, "capabilities")
        if installed:
            print(f"\n## installed capabilities ({len(installed)})")
            for cap in installed:
                ref = cap.get("ref", "")
                cap_type_label = cap.get("type", "")
                print(f"  {ref}" + (f" [{cap_type_label}]" if cap_type_label else ""))
    return 0


def handle_capability_inventory(args: argparse.Namespace) -> int:
    """Show or regenerate INVENTORY.md from installed registry state."""
    root = Path(args.root).expanduser()
    content = inventory_markdown(_installed_registry_payloads(root))
    if getattr(args, "regenerate", False):
        from ..scaffold import harness_path

        target = harness_path(root) / "INVENTORY.md"
        before = target.read_text(encoding="utf-8") if target.is_file() else None
        if before == content:
            print("INVENTORY.md already up to date")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            print(f"updated: {target}")
    else:
        inventory_path = root / "harness" / "INVENTORY.md"
        if inventory_path.exists():
            print(inventory_path.read_text(encoding="utf-8"))
        else:
            print(content)
    return 0


def register(subparsers) -> None:
    """Register the capability command group."""
    capability_parser = subparsers.add_parser("capability", help="Inspect installed OS capabilities.")
    capability_subparsers = capability_parser.add_subparsers(dest="capability_command", required=True)
    capability_list_parser = capability_subparsers.add_parser("list", help="List capabilities from installed registry.")
    capability_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    capability_list_parser.add_argument("--type", dest="type", help="Filter by capability type (e.g. commands, skills, mcp_servers).")
    capability_list_parser.set_defaults(handler=handle_capability_list)
    capability_inventory_parser = capability_subparsers.add_parser("inventory", help="Show or regenerate INVENTORY.md.")
    capability_inventory_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    capability_inventory_parser.add_argument("--regenerate", action="store_true", help="Rewrite INVENTORY.md from current registry state.")
    capability_inventory_parser.set_defaults(handler=handle_capability_inventory)
