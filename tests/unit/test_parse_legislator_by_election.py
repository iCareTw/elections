from pathlib import Path

import openpyxl

from src.parse_legislator_by_election import parse_file


def test_parse_file_reads_vote_year_and_region_from_by_election_xlsx(tmp_path: Path) -> None:
    path = tmp_path / "8th" / "第8屆立法委員臺中市第02選舉區補選.xlsx"
    path.parent.mkdir(parents=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(("投票日", "地區", "號次", "姓名", "性別", "出生年", "政黨", "得票數", "得票率", "當選"))
    ws.append(("2013-01-26", "選舉區", 1, "顏寬恒", "1", "1977", "中國國民黨", 66457, 49.95, "*"))
    wb.save(path)

    assert parse_file(path) == [
        {
            "name": "顏寬恒",
            "birthday": 1977,
            "year": 2013,
            "session": 8,
            "type": "立法委員",
            "region": "臺中市第02選舉區",
            "party": "中國國民黨",
            "elected": 1,
        }
    ]


def test_parse_file_uses_top_ticket_when_no_victor_mark_exists(tmp_path: Path) -> None:
    path = tmp_path / "7th" / "第7屆立法委員南投縣第01選舉區補選.xlsx"
    path.parent.mkdir(parents=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(("投票日", "地區", "號次", "姓名", "性別", "出生年", "政黨", "得票數", "得票率", "當選"))
    ws.append(("2009-12-05", "選舉區", 1, "馬文君", "2", "1965", "中國國民黨", 65922, 55.26, " "))
    ws.append(("2009-12-05", "選舉區", 2, "林耘生", "1", "1972", "民主進步黨", 53362, 44.74, " "))
    wb.save(path)

    rows = parse_file(path)

    assert rows[0]["elected"] == 1
    assert rows[1]["elected"] == 0
