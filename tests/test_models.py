"""Tests for app.models (F11): the ExtractRequest wire contract.

The `output_schema` field-validator wires the F11 subset gate, so a bad schema
surfaces as a Pydantic ValidationError — which FastAPI renders as 422 in F16.
"""

import pytest
from pydantic import ValidationError

from app.models import ExtractRequest


def test_valid_request_builds_with_defaults() -> None:
    req = ExtractRequest(url="https://example.com/products", prompt="get titles")
    assert req.prompt == "get titles"
    assert req.render is False
    assert req.output_schema is None
    assert req.provider is None


def test_bad_url_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(url="not-a-url", prompt="x")


def test_empty_prompt_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(url="https://example.com", prompt="")


def test_valid_output_schema_accepted() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    req = ExtractRequest(
        url="https://example.com", prompt="x", output_schema=schema, render=True
    )
    assert req.output_schema == schema
    assert req.render is True


def test_root_non_object_output_schema_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(
            url="https://example.com",
            prompt="x",
            output_schema={"type": "array", "items": {"type": "string"}},
        )


def test_out_of_subset_output_schema_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(
            url="https://example.com",
            prompt="x",
            output_schema={"type": "object", "not": {"type": "string"}},
        )
