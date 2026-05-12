from __future__ import annotations

from src.webapp.identity_checks import find_identity_check_issues, region_root


def test_find_identity_check_issues_detects_same_year_multiple() -> None:
    issues = find_identity_check_issues([
        {
            "id": "id_劉煜基_1946",
            "name": "劉煜基",
            "birthday": 1946,
            "elections": [
                {
                    "source_record_id": "legislator:1",
                    "year": 1998,
                    "type": "立法委員",
                    "region": "屏東縣選舉區",
                    "elected": 0,
                },
                {
                    "source_record_id": "council:1",
                    "year": 1998,
                    "type": "縣市議員",
                    "region": "屏東縣 第03選舉區",
                    "elected": 0,
                },
            ],
        }
    ])

    assert [issue["issue_type"] for issue in issues] == ["same_year_multiple"]
    assert issues[0]["severity"] == "critical"
    assert issues[0]["source_record_ids"] == ["legislator:1", "council:1"]


def test_find_identity_check_issues_detects_downgrade_after_elected() -> None:
    issues = find_identity_check_issues([
        {
            "id": "id_測試人_1970",
            "name": "測試人",
            "birthday": 1970,
            "elections": [
                {
                    "source_record_id": "legislator:1",
                    "year": 2016,
                    "type": "立法委員",
                    "region": "臺北市 第04選舉區",
                    "elected": 1,
                },
                {
                    "source_record_id": "council:1",
                    "year": 2022,
                    "type": "縣市議員",
                    "region": "臺北市 第02選舉區",
                    "elected": 1,
                },
            ],
        }
    ])

    assert [issue["issue_type"] for issue in issues] == ["rank_downgrade"]


def test_region_root_treats_county_city_renames_as_same_region() -> None:
    assert region_root("臺北縣 第05選舉區") == "新北市"
    assert region_root("新北市 第03選舉區") == "新北市"
