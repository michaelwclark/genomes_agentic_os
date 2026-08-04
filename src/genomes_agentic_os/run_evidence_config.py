"""Canonical run-evidence model registry loading and validation.

This module owns configuration shape only. Storage adapters and ingestion
services consume the validated mapping through dependency injection.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


class RunEvidenceConfigurationError(ValueError):
    """Raised when the canonical run-evidence registry is invalid."""


def load_run_evidence_config(root: Path) -> dict[str, Any]:
    """Load and validate ``harness/config/run-evidence.yml`` from *root*."""
    config_path = root / "harness" / "config" / "run-evidence.yml"
    schema_path = root / "harness" / "schemas" / "run-evidence-config.schema.json"
    if not schema_path.is_file():
        schema_path = Path(__file__).parents[2] / "schemas" / "run-evidence-config.schema.json"
    if not config_path.is_file():
        raise RunEvidenceConfigurationError(f"run evidence config is missing: {config_path}")
    if not schema_path.is_file():
        raise RunEvidenceConfigurationError(f"run evidence schema is missing: {schema_path}")

    document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise RunEvidenceConfigurationError("run evidence config must be a mapping")
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "root"
        raise RunEvidenceConfigurationError(f"run evidence config invalid at {location}: {first.message}")
    models = document["models"]
    priorities = [model["routing_priority"] for model in models.values()]
    if len(priorities) != len(set(priorities)):
        raise RunEvidenceConfigurationError("run evidence model routing_priority values must be unique")
    configured_keys = set(models)
    for writer_key, writer in document["writers"].items():
        unknown = set(writer["model_keys"]) - configured_keys
        if unknown:
            raise RunEvidenceConfigurationError(
                f"run evidence writer {writer_key} references unknown models: {', '.join(sorted(unknown))}"
            )
    return dict(document)


def configured_model_keys(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return deterministic model keys from an already validated mapping."""
    models = config.get("models")
    if not isinstance(models, Mapping):
        raise RunEvidenceConfigurationError("run evidence models must be a mapping")
    return tuple(sorted(str(key) for key in models))
