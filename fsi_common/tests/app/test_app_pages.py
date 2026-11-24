"""Answer pages and tables: sorting, the export, and the limit on tiles."""

from __future__ import annotations

import csv
import io

import pytest

from fsi_common.app.pages import (
    Answer,
    Cell,
    Column,
    Tile,
    build_table,
    natural_key,
    sort_rows,
    table_csv,
)

COLUMNS = [Column("para", "Paragraph"), Column("kind", "Kind")]


def _rows(*pairs):
    return [{"para": Cell(p), "kind": Cell(k)} for p, k in pairs]


def _href(**kw):
    return "/t?" + "&".join(f"{k}={v}" for k, v in kw.items())


def test_an_answer_with_four_tiles_is_refused():
    tiles = tuple(Tile(label=str(i), value=str(i)) for i in range(4))
    with pytest.raises(ValueError, match="at most 3 tiles, not 4"):
        Answer(sentence="x", tiles=tiles)


def test_natural_order_puts_7_2_before_7_10():
    assert sorted(["7.10", "7.2", "10.1", "2.1"], key=natural_key) == ["2.1", "7.2", "7.10", "10.1"]


def test_sort_rows_orders_by_the_column_in_both_directions_and_is_stable():
    rows = _rows(("7.10", "b"), ("7.2", "a"), ("7.2", "c"))
    up = [r["para"].text + r["kind"].text for r in sort_rows(rows, "para")]
    assert up == ["7.2a", "7.2c", "7.10b"]
    down = [r["para"].text for r in sort_rows(rows, "para", descending=True)]
    assert down == ["7.10", "7.2", "7.2"]


def test_an_unknown_sort_key_keeps_the_order_given():
    rows = _rows(("b", "x"), ("a", "y"))
    assert sort_rows(rows, "nope") == rows
    assert sort_rows(rows, None) == rows


def test_build_table_marks_the_sorted_column_and_links_the_opposite_direction():
    view = build_table(
        COLUMNS,
        _rows(("7.10", "b"), ("7.2", "a")),
        sort="para",
        descending=False,
        href_for=_href,
        export_href="/t.csv",
        caption="Facts",
    )
    assert [h.sorted_as for h in view.headers] == ["ascending", "none"]
    assert view.headers[0].href == "/t?sort=para&dir=desc"
    assert view.headers[1].href == "/t?sort=kind&dir=asc"
    assert [r["para"].text for r in view.rows] == ["7.2", "7.10"]


def test_the_csv_holds_the_rows_in_the_order_the_table_shows_them():
    view = build_table(
        COLUMNS,
        _rows(("7.10", "b"), ("7.2", "a")),
        sort="para",
        descending=True,
        href_for=_href,
        export_href="/t.csv",
        caption="Facts",
    )
    parsed = list(csv.reader(io.StringIO(table_csv(view))))
    assert parsed == [["Paragraph", "Kind"], ["7.10", "b"], ["7.2", "a"]]


def test_a_cell_that_a_spreadsheet_would_run_is_written_as_text():
    view = build_table(
        COLUMNS,
        _rows(("=HYPERLINK(1)", "+1"), ("-2", "@x")),
        sort=None,
        descending=False,
        href_for=_href,
        export_href="/t.csv",
        caption="Facts",
    )
    parsed = list(csv.reader(io.StringIO(table_csv(view))))
    assert parsed[1:] == [["'=HYPERLINK(1)", "'+1"], ["'-2", "'@x"]]


def test_an_empty_table_still_exports_its_headings():
    view = build_table(
        COLUMNS, [], sort=None, descending=False, href_for=_href, export_href="/t.csv", caption="x"
    )
    assert table_csv(view) == "Paragraph,Kind\r\n"
