"""Contract test: jsonschema — validates the API surface used by this project.

Source usage (src/genomes_agentic_os):
  import jsonschema; jsonschema.Draft202012Validator(schema).iter_errors(doc)
  from jsonschema import Draft202012Validator, FormatChecker

If a jsonschema upgrade breaks any assertion here, our usage must be updated
before the dependency bump can merge.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator, FormatChecker

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_draft202012validator_is_reachable_from_module_and_import() -> None:
    assert jsonschema.Draft202012Validator is Draft202012Validator


def test_iter_errors_accepts_valid_documents() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    assert list(Draft202012Validator(schema).iter_errors({"name": "ok"})) == []


def test_iter_errors_flags_invalid_documents_with_messages() -> None:
    schema = {"type": "object", "required": ["name"], "additionalProperties": False}
    errors = list(Draft202012Validator(schema).iter_errors({"unexpected": 1}))
    assert errors
    assert all(isinstance(error.message, str) and error.message for error in errors)


def test_validator_accepts_format_checker_keyword() -> None:
    validator = Draft202012Validator(
        {"type": "string", "format": "date"}, format_checker=FormatChecker()
    )
    assert list(validator.iter_errors("2026-07-22")) == []
    assert list(validator.iter_errors("not-a-date"))


def test_repo_schemas_are_valid_draft_2020_12_schemas() -> None:
    # The CLI validates documents against these files with Draft202012Validator;
    # the schemas themselves must stay acceptable to check_schema.
    schema_files = sorted((_REPO_ROOT / "schemas").glob("*.schema.json"))
    assert schema_files, "expected bundled schemas under schemas/"
    for schema_file in schema_files:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
