"""Tests for app.extraction.schemas (F11).

Covers the submit-time subset gate (`validate_request_schema`), strict-mode
normalization (`normalize_for_strict`), and output validation against the user's
original schema with format checks on (`validate_output`).
"""

import pytest
from jsonschema.exceptions import ValidationError

from app.extraction.schemas import (
    InvalidSchemaError,
    normalize_for_strict,
    validate_output,
    validate_request_schema,
)

# --- validate_request_schema: the submit-time gate ---


def test_valid_subset_schema_accepted() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer", "minimum": 0},
            "tags": {"type": "array", "items": {"type": "string"}},
            "kind": {"enum": ["a", "b"]},
            "ref": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["name"],
    }
    validate_request_schema(schema)  # must not raise


def test_root_non_object_rejected() -> None:
    with pytest.raises(InvalidSchemaError):
        validate_request_schema({"type": "array", "items": {"type": "string"}})


def test_root_missing_type_rejected() -> None:
    with pytest.raises(InvalidSchemaError):
        validate_request_schema({"properties": {"a": {"type": "string"}}})


def test_malformed_schema_rejected() -> None:
    # `properties` must be an object — check_schema rejects this against the metaschema.
    with pytest.raises(InvalidSchemaError):
        validate_request_schema({"type": "object", "properties": "not-an-object"})


def test_top_level_unsupported_keyword_rejected() -> None:
    with pytest.raises(InvalidSchemaError):
        validate_request_schema(
            {"type": "object", "oneOf": [{"type": "object"}, {"type": "object"}]}
        )


def test_nested_unsupported_keyword_rejected() -> None:
    schema = {
        "type": "object",
        "properties": {"choice": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
    }
    with pytest.raises(InvalidSchemaError):
        validate_request_schema(schema)


def test_property_named_like_keyword_is_accepted() -> None:
    # `not`/`if` here are PROPERTY NAMES, not schema keywords — must not be rejected.
    schema = {
        "type": "object",
        "properties": {
            "not": {"type": "string"},
            "if": {"type": "integer"},
        },
    }
    validate_request_schema(schema)  # must not raise


def test_enum_const_values_are_not_treated_as_keywords() -> None:
    # Keyword-looking strings inside enum/const data must not trip the denylist.
    schema = {
        "type": "object",
        "properties": {
            "kind": {"enum": ["oneOf", "allOf", "not"]},
            "tag": {"const": "if"},
        },
    }
    validate_request_schema(schema)  # must not raise


# --- normalize_for_strict: deep-copied strict tool schema ---


def test_normalize_fills_object_nodes_recursively() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
            "tags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                },
            },
        },
    }
    out = normalize_for_strict(schema)

    assert out["additionalProperties"] is False
    assert set(out["required"]) == {"name", "address", "tags"}

    address = out["properties"]["address"]
    assert address["additionalProperties"] is False
    assert address["required"] == ["city"]

    item = out["properties"]["tags"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["label"]


def test_normalize_descends_anyof_and_defs() -> None:
    schema = {
        "type": "object",
        "properties": {
            "val": {
                "anyOf": [
                    {"type": "object", "properties": {"a": {"type": "string"}}},
                    {"type": "null"},
                ]
            }
        },
        "$defs": {"Item": {"type": "object", "properties": {"x": {"type": "integer"}}}},
    }
    out = normalize_for_strict(schema)

    anyof_obj = out["properties"]["val"]["anyOf"][0]
    assert anyof_obj["additionalProperties"] is False
    assert anyof_obj["required"] == ["a"]

    defs_obj = out["$defs"]["Item"]
    assert defs_obj["additionalProperties"] is False
    assert defs_obj["required"] == ["x"]


def test_normalize_does_not_mutate_input() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }
    normalize_for_strict(schema)
    assert "additionalProperties" not in schema
    assert "required" not in schema
    assert "additionalProperties" not in schema["properties"]["name"]


def test_normalize_leaves_non_object_and_propertyless_nodes_alone() -> None:
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    out = normalize_for_strict(schema)
    # A string leaf gets nothing added.
    assert "additionalProperties" not in out["properties"]["name"]
    assert "required" not in out["properties"]["name"]

    # An object node with no `properties` is left untouched (no all-reject schema).
    propertyless = normalize_for_strict({"type": "object"})
    assert "additionalProperties" not in propertyless
    assert "required" not in propertyless


# --- validate_output: against the ORIGINAL schema, with format checks ---


def test_validate_output_accepts_conforming_dict() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name", "age"],
    }
    validate_output({"name": "Ada", "age": 36}, schema=schema)  # must not raise


def test_validate_output_rejects_missing_required() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name", "age"],
    }
    with pytest.raises(ValidationError):
        validate_output({"name": "Ada"}, schema=schema)


def test_validate_output_rejects_wrong_type() -> None:
    schema = {
        "type": "object",
        "properties": {"age": {"type": "integer"}},
        "required": ["age"],
    }
    with pytest.raises(ValidationError):
        validate_output({"age": "not-an-int"}, schema=schema)


def test_validate_output_enforces_format() -> None:
    # Proves FORMAT_CHECKER is active: plain jsonschema.validate would NOT catch this.
    schema = {
        "type": "object",
        "properties": {"email": {"type": "string", "format": "email"}},
        "required": ["email"],
    }
    validate_output({"email": "person@example.com"}, schema=schema)  # must not raise
    with pytest.raises(ValidationError):
        validate_output({"email": "not-an-email"}, schema=schema)


def test_validate_output_accepts_list_envelope() -> None:
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
        "required": ["items"],
    }
    validate_output({"items": ["a", "b"]}, schema=schema)  # must not raise
