"""Validate and normalize the request's JSON Schema, and validate LLM output.

Pure schema logic only — no network, no job state, no LLM SDK. The request
`output_schema` is used as-is (never turned into a Pydantic model): validated for
the supported subset at submit time, normalized into the provider's strict tool
schema, and used to validate the LLM's returned dict.
"""

import copy
from collections.abc import Iterator
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

# Keywords outside the supported subset. Rejected anywhere they appear as a schema
# keyword (not as a property name — see `_iter_subschemas`). Bounds (minimum/maxLength)
# are intentionally absent: we accept and validate them, the provider just may ignore.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "oneOf",
        "allOf",
        "not",
        "if",
        "then",
        "else",
        "contains",
        "prefixItems",
        "patternProperties",
        "dependentSchemas",
        "dependentRequired",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
    }
)

# Schema positions to descend into. Keys inside the *map* keywords are names, not
# keywords; data-valued keywords (`enum`, `const`, `default`) are never descended.
_SUBSCHEMA_KEYS = (
    "items",
    "additionalProperties",
    "not",
    "contains",
    "propertyNames",
    "if",
    "then",
    "else",
    "unevaluatedItems",
    "unevaluatedProperties",
)
_SUBSCHEMA_LIST_KEYS = ("anyOf", "allOf", "oneOf", "prefixItems")
_SUBSCHEMA_MAP_KEYS = (
    "properties",
    "$defs",
    "definitions",
    "patternProperties",
    "dependentSchemas",
)


class InvalidSchemaError(ValueError):
    """The request `output_schema` is malformed or outside the supported subset.

    Subclasses `ValueError` so a Pydantic field validator surfaces it as a 422.
    """


def _iter_subschemas(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield `schema` and every nested subschema, descending only schema positions.

    Lookups are by known keyword, never by iterating arbitrary keys, so property
    names (e.g. a field literally named `not`) are not mistaken for keywords and
    `enum`/`const` data values are never traversed.
    """
    yield schema
    for key in _SUBSCHEMA_KEYS:
        child = schema.get(key)
        if isinstance(child, dict):
            yield from _iter_subschemas(child)
    for key in _SUBSCHEMA_LIST_KEYS:
        children = schema.get(key)
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    yield from _iter_subschemas(child)
    for key in _SUBSCHEMA_MAP_KEYS:
        mapping = schema.get(key)
        if isinstance(mapping, dict):
            for child in mapping.values():
                if isinstance(child, dict):
                    yield from _iter_subschemas(child)


def validate_request_schema(schema: dict[str, Any]) -> None:
    """Reject a malformed, root-non-object, or out-of-subset `output_schema`.

    Raises `InvalidSchemaError` (a `ValueError`) so the API boundary returns 422.
    """
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise InvalidSchemaError(
            f"output_schema is not a valid JSON Schema: {exc.message}"
        ) from exc
    if schema.get("type") != "object":
        raise InvalidSchemaError("output_schema root must be of type 'object'")
    for node in _iter_subschemas(schema):
        for keyword in node:
            if keyword in _UNSUPPORTED_KEYWORDS:
                raise InvalidSchemaError(
                    f"output_schema uses unsupported keyword '{keyword}'"
                )


def normalize_for_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy with strict-mode fields filled, leaving `schema` untouched.

    Every object node that declares `properties` gets `additionalProperties: false`
    and `required: [all property names]`, so the provider's strict tool conforms.
    """
    clone = copy.deepcopy(schema)
    for node in list(_iter_subschemas(clone)):
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
    return clone


def validate_output(data: dict[str, Any], *, schema: dict[str, Any]) -> None:
    """Validate `data` against the user's original `schema`, with format checks on.

    Uses `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate`
    ignores `format`). Raises jsonschema `ValidationError` on mismatch; the
    extraction engine maps that to a readable job/provider error.
    """
    validator = Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    validator.validate(data)
