"""Integration test: candidates.yaml 總統副總統資料 vs _data/president/ xlsx 原始資料。"""

import yaml
import pytest
from pathlib import Path

from src.normalize import normalize_name
from src.parse_president import parse_file

CANDIDATES_YAML = Path("candidates.yaml")
PRESIDENT_DIR = Path("_data/president")
PRESIDENT_TYPES = {"國家元首_總統", "國家元首_副總統"}

# xlsx 原始資料刊登疏失，已知錯誤，跳過 birthday 比對
# key: (year, election_type, ticket)
KNOWN_BIRTHDAY_ERRORS: set[tuple] = {
    (2000, "國家元首_副總統", 2),  # 蕭萬長 10th 誤植為 1942, 正確為 1939
}


def _parse_xlsx(year: int) -> list[dict]:
    """從 xlsx 解析該年度所有總統副總統候選人（黨籍正規化由 parse_file 處理）。"""
    n = (year - 1996) // 4 + 9
    path = PRESIDENT_DIR / f"第{n:02d}任總統副總統選舉.xlsx"
    return [
        {**r, "name": normalize_name(r["name"])}
        for r in parse_file(path)
    ]


def _load_yaml_entries() -> list[dict]:
    """從 candidates.yaml 取出所有總統副總統參選紀錄。"""
    with open(CANDIDATES_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    entries = []
    for candidate in data:
        for election in candidate.get("elections", []):
            if election["type"] in PRESIDENT_TYPES:
                entries.append({
                    "name": normalize_name(candidate["name"]),
                    "birthday": candidate.get("birthday"),
                    "year": election["year"],
                    "type": election["type"],
                    "ticket": election["ticket"],
                    "party": election["party"],
                    "elected": election["elected"],
                })
    return entries


def _get_yaml_years() -> list[int]:
    return sorted({e["year"] for e in _load_yaml_entries()})


@pytest.mark.parametrize("year", _get_yaml_years())
@pytest.mark.parametrize("election_type", sorted(PRESIDENT_TYPES))
def test_president_candidates_match_xlsx(year: int, election_type: str) -> None:
    xlsx = {
        c["ticket"]: c
        for c in _parse_xlsx(year)
        if c["type"] == election_type
    }
    yaml_entries = {
        e["ticket"]: e
        for e in _load_yaml_entries()
        if e["year"] == year and e["type"] == election_type
    }

    yaml_tickets = set(yaml_entries.keys())
    xlsx_tickets = set(xlsx.keys())

    # 要馬全部都要有，要馬全部都沒有
    assert yaml_tickets in (set(), xlsx_tickets), (
        f"{year} 年 {election_type} 資料不完整\n"
        f"  xlsx: {sorted(xlsx_tickets)}\n"
        f"  yaml: {sorted(yaml_tickets)}\n"
        f"  缺漏: {sorted(xlsx_tickets - yaml_tickets)}"
    )

    for ticket, x in xlsx.items():
        if ticket not in yaml_entries:
            continue
        y = yaml_entries[ticket]
        assert x["name"] == y["name"], f"{year}/{election_type}/號次{ticket}: 姓名不符 xlsx={x['name']!r} yaml={y['name']!r}"
        assert x["party"] == y["party"], f"{year}/{election_type}/號次{ticket}: 政黨不符 xlsx={x['party']!r} yaml={y['party']!r}"
        assert x["elected"] == y["elected"], f"{year}/{election_type}/號次{ticket}: 當選不符 xlsx={x['elected']} yaml={y['elected']}"
        if (year, election_type, ticket) not in KNOWN_BIRTHDAY_ERRORS:
            assert x["birthday"] == y["birthday"], f"{year}/{election_type}/號次{ticket}: 生日不符 xlsx={x['birthday']} yaml={y['birthday']}"
