import io

import openpyxl

from src.cec_attachment import parse_votes_xls


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sheet(no_row: list, name_row: list, party_row: list, total_row: list) -> bytes:
    return _xlsx_bytes([["表2"], ["某某補選"], ["行政區別", "各候選人得票情形"], no_row, name_row, party_row, total_row])


def test_parse_reads_bracketed_candidate_numbers_and_text_votes() -> None:
    records = parse_votes_xls(
        _sheet(
            [None, "(1)", "(2)", "(3)"],
            [None, "陳源奇", "何志偉", "王奕凱"],
            [None, "全民無黨聯盟", "民主進步黨", "  "],
            ["總計", "89", "38591", "897"],
        ),
        "2019-01-27",
        "第9屆立法委員臺北市第02選舉區缺額補選",
    )

    assert [(r["cand_no"], r["cand_name"], r["party_name"], r["ticket_num"]) for r in records] == [
        (1, "陳源奇", "全民無黨聯盟", 89),
        (2, "何志偉", "民主進步黨", 38591),
        (3, "王奕凱", "無黨籍", 897),
    ]
    assert [r["is_victor"] for r in records] == [" ", "*", " "]
    assert records[0]["vote_date"] == "2019-01-27"


def test_parse_reads_plain_numeric_candidate_numbers() -> None:
    records = parse_votes_xls(
        _sheet(
            [None, 1, 2],
            [None, "吳怡農", "王鴻薇"],
            [None, "民主進步黨", "中國國民黨"],
            ["總計", 54739, 60519],
        ),
        "2023-01-08",
        "第10屆立法委員臺北市第3選舉區缺額補選",
    )

    assert [r["cand_name"] for r in records] == ["吳怡農", "王鴻薇"]
    assert [r["is_victor"] for r in records] == [" ", "*"]


def test_parse_returns_empty_when_layout_is_unrecognised() -> None:
    assert parse_votes_xls(_xlsx_bytes([["表1"], ["概況"], ["選舉人數", 100]]), "2019-01-27", "x") == []
