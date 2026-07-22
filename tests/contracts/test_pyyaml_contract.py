"""Contract test: PyYAML — validates the API surface used by this project.

Source usage (src/genomes_agentic_os):
  yaml.safe_load / yaml.safe_dump (with sort_keys=..., allow_unicode=True)
  yaml.YAMLError
  yaml.load(text, Loader=<subclass of yaml.SafeLoader>)
  yaml.SafeLoader subclassing + add_constructor
  yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG
  from yaml.constructor import ConstructorError  (4-arg raise shape)
  from yaml.nodes import MappingNode

If a PyYAML upgrade breaks any assertion here, our usage must be updated
before the dependency bump can merge.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode


def test_safe_dump_and_safe_load_round_trip() -> None:
    doc = {"name": "agentic-os", "count": 3, "nested": {"enabled": True}, "items": ["a", "b"]}
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    assert yaml.safe_load(text) == doc


def test_safe_dump_accepts_sort_keys_true() -> None:
    text = yaml.safe_dump({"b": 1, "a": 2}, sort_keys=True)
    assert text.index("a:") < text.index("b:")


def test_safe_load_raises_yamlerror_on_malformed_input() -> None:
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("key: [unclosed")


def test_safe_loader_subclass_with_custom_mapping_constructor() -> None:
    # Mirrors the duplicate-key-detecting loaders in src/genomes_agentic_os:
    # subclass yaml.SafeLoader, register a constructor for the default mapping
    # tag, and load via yaml.load(text, Loader=...).
    seen_nodes: list[MappingNode] = []

    class _ContractLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader: yaml.SafeLoader, node: MappingNode) -> dict[Any, Any]:
        assert isinstance(node, MappingNode)
        seen_nodes.append(node)
        return loader.construct_mapping(node)

    _ContractLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
    )
    parsed = yaml.load("a: 1\nb: 2\n", Loader=_ContractLoader)
    assert parsed == {"a": 1, "b": 2}
    assert seen_nodes, "custom constructor was not invoked with a MappingNode"


def test_mapping_nodes_expose_start_mark_for_error_reporting() -> None:
    class _ProbeLoader(yaml.SafeLoader):
        pass

    marks: list[Any] = []

    def _construct_mapping(loader: yaml.SafeLoader, node: MappingNode) -> dict[Any, Any]:
        marks.append(node.start_mark)
        return loader.construct_mapping(node)

    _ProbeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
    )
    yaml.load("a: 1\n", Loader=_ProbeLoader)
    assert marks and marks[0] is not None


def test_constructor_error_supports_the_four_argument_raise_shape() -> None:
    # src raises ConstructorError(context, context_mark, problem, problem_mark).
    error = ConstructorError("while constructing a mapping", None, "found duplicate key", None)
    assert issubclass(ConstructorError, yaml.YAMLError)
    assert "while constructing a mapping" in str(error)
