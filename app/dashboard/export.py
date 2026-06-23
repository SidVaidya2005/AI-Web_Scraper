"""Serialize a finished job's result dict to a downloadable JSON or CSV string.

Pure formatting only — no FastAPI, no job state, no I/O. `Job.result` is always an
object envelope (a dict); a list extraction is wrapped under a single key
(`{"items": [...]}`). CSV turns a single-key list-of-objects envelope into one row
per object (columns = union of keys, first-seen order); any other shape becomes a
single row (columns = the dict's keys). Nested values are JSON-encoded, and cells
that look like spreadsheet formulas are neutralized (CSV-injection defense).
"""

import csv
import io
import json
from typing import Any

# Cells starting with one of these are executed by spreadsheet apps — prefix with an
# apostrophe so the value is shown as literal text instead (CSV-injection defense).
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def result_to_json(result: dict[str, Any]) -> str:
    """Return `result` as a pretty-printed JSON document."""
    return json.dumps(result, indent=2, ensure_ascii=False)


def result_to_csv(result: dict[str, Any]) -> str:
    """Return `result` as CSV text (header + rows); see the module docstring."""
    rows = _rows_for(result)
    columns = _columns_for(rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([_escape_formula(col) for col in columns])
    for row in rows:
        writer.writerow(
            [_escape_formula(_render_cell(row.get(col))) for col in columns]
        )
    return buffer.getvalue()


def _rows_for(result: dict[str, Any]) -> list[dict[str, Any]]:
    """A single-key list-of-objects envelope → its objects; any other shape → one row.

    An empty result, or a single-key envelope whose list is empty, yields no rows
    (the CSV is a header-only line). A single key holding a list of *scalars* is not
    an envelope — it stays one row with the list JSON-encoded in its cell.
    """
    if len(result) == 1:
        (only_value,) = result.values()
        if isinstance(only_value, list) and all(
            isinstance(item, dict) for item in only_value
        ):
            return only_value  # list of dicts → rows; empty list → [] (header only)
    return [result] if result else []


def _columns_for(rows: list[dict[str, Any]]) -> list[str]:
    """Union of keys across `rows`, preserving first-seen order."""
    columns: dict[str, None] = {}  # insertion-ordered set: dedupe, keep first seen
    for row in rows:
        for key in row:
            columns.setdefault(key, None)
    return list(columns)


def _render_cell(value: Any) -> str:
    """Render a cell value as text: dict/list → JSON, None → empty, else `str`."""
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _escape_formula(text: str) -> str:
    """Prefix a formula-trigger cell with `'` so a spreadsheet shows it as text."""
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text
