"""Tests for app/dashboard/export.py — pure JSON/CSV serialization of a job result.

CSV shape rules (see the module docstring): a single-key list-of-objects envelope
becomes one row per object (columns = union of keys, first-seen order); any other
shape is a single row; nested values are JSON-encoded; formula-looking cells are
neutralized. Tests parse the CSV back with `csv.reader` so they assert on values,
not on quoting details.
"""

import csv
import io
import json

from app.dashboard import export


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_json_round_trips_to_input() -> None:
    result = {"items": [{"a": 1}, {"a": 2, "b": 3}]}
    assert json.loads(export.result_to_json(result)) == result


def test_csv_list_envelope_multi_row_union_columns() -> None:
    result = {"items": [{"a": 1}, {"a": 2, "b": 3}]}
    rows = _parse_csv(export.result_to_csv(result))
    assert rows[0] == ["a", "b"]  # union of keys, first-seen order
    assert rows[1] == ["1", ""]  # missing `b` → blank cell
    assert rows[2] == ["2", "3"]


def test_csv_single_object_one_row() -> None:
    rows = _parse_csv(export.result_to_csv({"title": "x", "price": 5}))
    assert rows == [["title", "price"], ["x", "5"]]


def test_csv_list_of_scalars_is_single_row_with_json_cell() -> None:
    # A single key holding a list of scalars is NOT an envelope — one row, JSON cell.
    rows = _parse_csv(export.result_to_csv({"tags": ["x", "y"]}))
    assert rows[0] == ["tags"]
    assert rows[1] == [json.dumps(["x", "y"])]


def test_csv_nested_values_are_json_encoded() -> None:
    result = {"items": [{"meta": {"k": "v"}, "vals": [1, 2]}]}
    rows = _parse_csv(export.result_to_csv(result))
    assert rows[0] == ["meta", "vals"]
    assert rows[1] == [json.dumps({"k": "v"}), json.dumps([1, 2])]


def test_csv_empty_result_is_header_only() -> None:
    rows = _parse_csv(export.result_to_csv({}))
    assert rows in ([], [[]])  # an empty header line, no data rows, no crash


def test_csv_empty_list_envelope_is_header_only() -> None:
    rows = _parse_csv(export.result_to_csv({"items": []}))
    assert rows in ([], [[]])


def test_csv_formula_injection_neutralized() -> None:
    for trigger in ("=", "+", "-", "@"):
        rows = _parse_csv(export.result_to_csv({"v": f"{trigger}SUM(A1)"}))
        assert rows[1][0] == f"'{trigger}SUM(A1)"


def test_csv_safe_cell_not_prefixed() -> None:
    rows = _parse_csv(export.result_to_csv({"v": "hello"}))
    assert rows[1][0] == "hello"


def test_csv_quotes_commas_and_newlines_round_trip() -> None:
    rows = _parse_csv(export.result_to_csv({"v": 'a,b"c\nd'}))
    assert rows[1][0] == 'a,b"c\nd'  # csv.reader unquotes back to the original


def test_csv_none_cell_is_blank() -> None:
    rows = _parse_csv(export.result_to_csv({"items": [{"a": None}]}))
    assert rows[1] == [""]
