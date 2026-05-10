from pathlib import Path

import openpyxl

from src.parse_indigenous import parse_chief_file, parse_rep_file


def _write_source(path: Path) -> None:
    path.parent.mkdir(parents=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["地區", "號次", "姓名", "性別", "出生年", "政黨", "得票數", "得票率", "當選"])
    ws.append(["烏來區", 1, "測試候選人", "男", 1970, "無黨籍及未經政黨推薦", 1000, 55.5, "*"])
    wb.save(path)


def test_parse_chief_file_reads_indigenous_chief_records(tmp_path: Path) -> None:
    path = tmp_path / "_data" / "indigenous_chief" / "2014" / "新北市.xlsx"
    _write_source(path)

    assert parse_chief_file(path) == [
        {
            "name": "測試候選人",
            "birthday": 1970,
            "year": 2014,
            "type": "原住民區長",
            "region": "新北市 烏來區",
            "party": "無黨籍",
            "elected": 1,
        }
    ]


def test_parse_rep_file_reads_indigenous_rep_records(tmp_path: Path) -> None:
    path = tmp_path / "_data" / "indigenous_rep" / "2014" / "新北市.xlsx"
    _write_source(path)

    records = parse_rep_file(path)

    assert records[0]["type"] == "原住民區民代表"
    assert records[0]["region"] == "新北市 烏來區"
