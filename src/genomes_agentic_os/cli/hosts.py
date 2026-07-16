"""CLI commands for the installed SSH host registry."""

from __future__ import annotations

import argparse

from ..hosts import format_host_routing_status, host_routing_status, list_hosts, upsert_host

from ._shared import DEFAULT_ROOT


def handle_host_add(args: argparse.Namespace) -> int:
    result = upsert_host(
        args.root,
        args.alias,
        ssh_alias=getattr(args, "ssh_alias", None),
        user=getattr(args, "user", None),
        home=getattr(args, "home", None),
        description=getattr(args, "description", None),
    )
    print(f"{result['action']}: {result['alias']} → {result['path']}")
    return 0


def handle_host_list(args: argparse.Namespace) -> int:
    hosts = list_hosts(args.root)
    if getattr(args, "json", False):
        import json

        print(json.dumps({"api_version": "host-list/v1", "hosts": hosts}, indent=2, sort_keys=True))
        return 0
    if not hosts:
        print("No hosts registered. Use: agentic-os host add <alias>")
        return 0
    for entry in hosts:
        alias = entry.get("alias", "")
        ssh_alias = entry.get("ssh_alias", alias)
        home = entry.get("home", "")
        desc = entry.get("description", "")
        home_part = f"  home: {home}" if home else ""
        print(f"  {alias}  (ssh_alias: {ssh_alias}){home_part}  {desc}")
    return 0


def handle_host_routing(args: argparse.Namespace) -> int:
    result = host_routing_status(args.root, recent_runs=getattr(args, "recent_runs", 8))
    if getattr(args, "json", False):
        import json

        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_host_routing_status(result))
    return 0


def register(subparsers) -> None:
    """Register the host command group."""
    host_parser = subparsers.add_parser("host", help="Manage the installed SSH host registry.")
    host_subparsers = host_parser.add_subparsers(dest="host_command", required=True)
    host_add = host_subparsers.add_parser("add", help="Add or update a host alias in the registry.")
    host_add.add_argument("alias", help="Host alias (identifier used in project remotes).")
    host_add.add_argument("--ssh-alias", help="SSH alias that resolves via ~/.ssh/config.")
    host_add.add_argument("--user", help="Remote username (informational).")
    host_add.add_argument("--home", help="Absolute home/path-domain root on this host.")
    host_add.add_argument("--description", help="Human-readable description of this host.")
    host_add.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_add.set_defaults(handler=handle_host_add)
    host_list = host_subparsers.add_parser("list", help="List registered hosts.")
    host_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    host_list.set_defaults(handler=handle_host_list)
    host_routing = host_subparsers.add_parser(
        "routing",
        help="Show cross-host routing policy and recent harness host receipts.",
    )
    host_routing.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    host_routing.add_argument("--recent-runs", type=int, default=8, help="Recent harness receipts to show.")
    host_routing.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    host_routing.set_defaults(handler=handle_host_routing)
