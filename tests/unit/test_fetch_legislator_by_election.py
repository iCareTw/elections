from pathlib import Path

import openpyxl

from src.fetch_legislator_by_election import (
    output_path,
    parse_by_election_items,
    ticket_loc,
    tickets_url,
    write_xlsx,
)


def test_output_path_groups_by_session() -> None:
    assert output_path(8, "第8屆立法委員臺中市第02選舉區補選") == Path(
        "_data/legislator/by-election-legislator/8th/第8屆立法委員臺中市第02選舉區補選.xlsx"
    )


def test_ticket_loc_uses_zero_location_for_county_level() -> None:
    assert ticket_loc({"data_level": "C"}) == "00_000_00_000_0000"


def test_ticket_loc_uses_theme_location_for_area_level() -> None:
    item = {
        "data_level": "A",
        "prv_code": "05",
        "city_code": "000",
        "area_code": "00",
        "dept_code": "000",
        "li_code": "0000",
    }

    assert ticket_loc(item) == "05_000_00_000_0000"


def test_tickets_url() -> None:
    item = {
        "type_id": "BEL",
        "subject_id": "L0",
        "legislator_type_id": "L1",
        "theme_id": "abc123",
        "data_level": "A",
        "prv_code": "05",
        "city_code": "000",
        "area_code": "00",
        "dept_code": "000",
        "li_code": "0000",
    }

    assert tickets_url(item) == (
        "https://db.cec.gov.tw/static/elections/data/tickets/BEL/L0/L1/"
        "abc123/A/05_000_00_000_0000.json"
    )


def test_write_xlsx_includes_vote_date(tmp_path: Path) -> None:
    path = tmp_path / "by-election.xlsx"
    write_xlsx(
        [
            {
                "vote_date": "2015-02-07",
                "area_name": "選舉區",
                "cand_no": 1,
                "cand_name": "測試",
                "cand_sex": "1",
                "cand_birthyear": "1970",
                "party_name": "測試黨",
                "ticket_num": 100,
                "ticket_percent": 50,
                "is_victor": "*",
            }
        ],
        path,
    )

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("投票日", "地區", "號次", "姓名", "性別", "出生年", "政黨", "得票數", "得票率", "當選")
    assert rows[1][0] == "2015-02-07"
    assert rows[1][3] == "測試"


def test_parse_by_election_items_keeps_district_items_regardless_of_has_data() -> None:
    """第 9、10 屆補選 has_data=false，資料只在附件裡，仍然要留下來。"""
    raw = [
        {
            "time_items": [
                {
                    "theme_items": [
                        {
                            "subject_id": "L0",
                            "legislator_type_id": "L1",
                            "session": 8,
                            "has_data": True,
                            "theme_id": "keep-tickets",
                        },
                        {
                            "subject_id": "L0",
                            "legislator_type_id": "L1",
                            "session": 9,
                            "has_data": False,
                            "theme_id": "keep-attachment",
                        },
                        {
                            "subject_id": "L0",
                            "legislator_type_id": "L2",
                            "session": 8,
                            "has_data": True,
                            "theme_id": "drop-not-l1",
                        },
                        {
                            "subject_id": "L0",
                            "legislator_type_id": "L1",
                            "session": 7,
                            "has_data": True,
                            "theme_id": "drop-other-session",
                        },
                    ]
                }
            ]
        }
    ]

    assert [item["theme_id"] for item in parse_by_election_items(raw, {8, 9})] == [
        "keep-tickets",
        "keep-attachment",
    ]


def test_roc_birthyear_reads_vertical_gazette_cell() -> None:
    from src.fetch_legislator_by_election import _roc_birthyear

    assert _roc_birthyear("57\n年\n08\n月\n30\n日") == 1968
    assert _roc_birthyear("民國44年6月10日") == 1955
    assert _roc_birthyear("") is None
    assert _roc_birthyear("不詳") is None


def _word(text: str, x: float, top: float) -> dict:
    return {"text": text, "x0": x, "x1": x + 20, "top": top}


def test_birthyear_is_read_from_the_column_next_to_the_vertical_name() -> None:
    from src.fetch_legislator_by_election import _birthyear_beside, _name_runs

    words = [
        _word("柯", 223, 309), _word("呈", 223, 346), _word("枋", 223, 383),
        _word("61", 280, 304), _word("11", 280, 352), _word("30", 280, 400),
        # 隔壁欄的其他數字不該被當成出生年
        _word("2019", 600, 300),
    ]
    runs = _name_runs(words, "柯呈枋")

    assert len(runs) == 1
    assert _birthyear_beside(words, runs[0]) == 1972


def test_name_runs_ignores_characters_that_are_not_stacked() -> None:
    from src.fetch_legislator_by_election import _name_runs

    words = [_word("柯", 223, 309), _word("呈", 500, 346), _word("枋", 223, 383)]

    assert _name_runs(words, "柯呈枋") == []
