"""Contract test: graphql-core — validates the API surface used by this project.

Source usage (src/genomes_agentic_os):
  from graphql import GraphQLError, build_schema, get_operation_ast,
      graphql_sync, parse, print_schema
  from graphql.language import OperationType

If a graphql-core upgrade breaks any assertion here, our usage must be
updated before the dependency bump can merge.
"""

from __future__ import annotations

import inspect

import graphql
import pytest
from graphql import (
    GraphQLError,
    build_schema,
    get_operation_ast,
    graphql_sync,
    parse,
    print_schema,
)
from graphql.language import OperationType

_SDL = """
type Query {
  hello: String
}
"""


def test_package_reports_a_version_string() -> None:
    assert isinstance(graphql.version, str)
    assert graphql.version


def test_entry_points_are_callable_and_error_type_is_an_exception() -> None:
    for entry_point in (build_schema, get_operation_ast, graphql_sync, parse, print_schema):
        assert callable(entry_point)
    assert issubclass(GraphQLError, Exception)


def test_build_schema_accepts_sdl_and_exposes_query_type() -> None:
    schema = build_schema(_SDL)
    assert schema.query_type is not None
    assert "hello" in schema.query_type.fields


def test_parse_and_get_operation_ast_report_operation_type() -> None:
    document = parse("query Fetch { hello }")
    operation = get_operation_ast(document)
    assert operation is not None
    assert operation.operation is OperationType.QUERY


def test_graphql_sync_executes_a_query_with_root_value() -> None:
    # Our callers pass root_value; confirm the keyword still exists.
    assert "root_value" in inspect.signature(graphql_sync).parameters
    result = graphql_sync(build_schema(_SDL), "{ hello }", root_value={"hello": "world"})
    assert result.errors is None
    assert result.data == {"hello": "world"}


def test_print_schema_round_trips_sdl() -> None:
    printed = print_schema(build_schema(_SDL))
    assert "type Query" in printed
    assert "hello: String" in printed


def test_parse_raises_graphql_error_on_invalid_documents() -> None:
    with pytest.raises(GraphQLError):
        parse("query {")
