"""Helpers shared by 3+ cli command-group modules (rule of three)."""

from __future__ import annotations


DEFAULT_ROOT = "~/agentic_os"


def print_result(result) -> None:
    messages = result.messages()
    if not messages:
        print("no changes")
        return
    for message in messages:
        print(message)


def yaml_dump(value) -> str:
    import yaml

    return yaml.safe_dump(value, sort_keys=False).strip()
