"""Acceptance test: candidates.yaml 總統副總統資料 vs _data/president/ xlsx 原始資料。"""

import yaml
import openpyxl
import pytest
from pathlib import Path

from src.normalize import normalize_name

CANDIDATES_YAML = Path("candidates.yaml")
PRESIDENT_DIR = Path("_data/president")
PRESIDENT_TYPES = {"國家元首_總統", "國家元首_副總統"}


def _year_to_ren(year: int) -> str:
    """CE 年份 → 任號 (zero-padded)。第09任 = 1996，每四年遞增。"""
    n = (year - 1996) // 4 + 9
    return f"{n:02d}"


def _parse_xlsx(year: int) -> list[dict]:
    """從 xlsx 解析該年度所有總統副總統候選人。"""
    ren = _year_to_ren(year)
    path = PRESIDENT_DIR / f"第{ren}任總統副總統選舉.xlsx"
    ws = openpyxl.load_workbook(path).active
    rows = list(ws.iter_rows(values_only=True))[1:]  # 略過 header

    candidates = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if row[2] is None:  # 號次為空 → 不是有效起始列
            i += 1
            continue

        ticket = int(row[2])
        party = str(row[5]) if row[5] else ""
        elected = 1 if str(row[8]).strip() == "*" else 0

        # 總統
        candidates.append({
            "name": normalize_name(str(row[1])),
            "type": "國家元首_總統",
            "ticket": ticket,
            "party": party,
            "elected": elected,
            "birthday": int(row[4]),
        })

        # 副總統（緊接下一列，號次為 None）
        if i + 1 < len(rows) and rows[i + 1][2] is None:
            vp = rows[i + 1]
            candidates.append({
                "name": normalize_name(str(vp[1])),
                "type": "國家元首_副總統",
                "ticket": ticket,
                "party": party,
                "elected": elected,
                "birthday": int(vp[4]),
            })
            i += 2
        else:
            i += 1

    return candidates


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
def test_president_candidates_match_xlsx(year: int) -> None:
    xlsx = {(c["type"], c["ticket"]): c for c in _parse_xlsx(year)}
    yaml_entries = {
        (e["type"], e["ticket"]): e
        for e in _load_yaml_entries()
        if e["year"] == year
    }

    assert set(xlsx.keys()) == set(yaml_entries.keys()), (
        f"{year} 年候選人組合不一致\n"
        f"  xlsx 有但 yaml 缺: {set(xlsx) - set(yaml_entries)}\n"
        f"  yaml 有但 xlsx 缺: {set(yaml_entries) - set(xlsx)}"
    )

    for key in xlsx:
        x, y = xlsx[key], yaml_entries[key]
        assert x["name"] == y["name"], f"{year}/{key}: 姓名不符 xlsx={x['name']!r} yaml={y['name']!r}"
        assert x["party"] == y["party"], f"{year}/{key}: 政黨不符 xlsx={x['party']!r} yaml={y['party']!r}"
        assert x["elected"] == y["elected"], f"{year}/{key}: 當選不符 xlsx={x['elected']} yaml={y['elected']}"
        assert x["birthday"] == y["birthday"], f"{year}/{key}: 生日不符 xlsx={x['birthday']} yaml={y['birthday']}"
