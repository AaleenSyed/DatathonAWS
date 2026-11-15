"""Validate objects against the schemas in contracts/openapi.yaml (OpenAPI 3.1 = JSON Schema 2020-12)."""
import functools
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

OPENAPI = Path(__file__).resolve().parents[1] / "contracts" / "openapi.yaml"


@functools.lru_cache(maxsize=1)
def spec() -> dict:
    return yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    # The spec is the root resource so "#/components/schemas/X" refs resolve; unknown top-level keys are ignored.
    schema = {**spec(), "$ref": f"#/components/schemas/{name}"}
    return Draft202012Validator(schema, format_checker=FormatChecker())


def errors(obj, name: str) -> list[str]:
    return [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in validator(name).iter_errors(obj)]


def assert_valid(obj, name: str):
    errs = errors(obj, name)
    assert not errs, f"{name} does not match the contract:\n" + "\n".join(errs[:10])
