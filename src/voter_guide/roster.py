"""中選會名冊 → 某一場選舉應該有哪些候選人。

公報解析的標準答案。`_data/` 裡本來就有中選會的候選人名冊(xlsx/yaml),
解析出來的姓名跟它對得上,才算這份公報讀成功;對不上就換下一個解析方法。

名冊只用來「驗收」,不會拿它的內容去補公報缺的欄位——公報有生日、學歷、
經歷、政見與相片,名冊沒有。
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

_LEGISLATOR_DISTRICT = ROOT / "_data/legislator/district-legislator"
_LEGISLATOR_PARTY = ROOT / "_data/legislator/party-list-legislator"
_LEGISLATOR_BY_ELECTION = ROOT / "_data/legislator/by-election-legislator"

# 民國年 → 屆次(名冊照屆次分目錄,公報照西元年)
_SESSION_YEARS = {2004: 6, 2008: 7, 2012: 8, 2016: 9, 2020: 10, 2024: 11}


def clean(name) -> str:
    return "".join(str(name).split())


def _rows(path: Path, by_election: bool = False) -> list[dict]:
    """名冊一列列讀出來。補選的 xlsx 欄位跟一般選舉不同,各有各的 parser。"""
    if path.suffix.lower() in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if by_election:
        from src.parse_legislator_by_election import parse_file
    else:
        from src.parse_legislator import parse_file
    try:
        return list(parse_file(path))
    except Exception:                    # 名冊格式歷屆不一,讀不動就當作沒有名冊
        return []


@lru_cache(maxsize=1)
def _legislator_index() -> dict[tuple, set[str]]:
    """(西元年, 區域名, 選舉區號) → 姓名集合。原住民與不分區各自成一個 key。"""
    index: dict[tuple, set[str]] = {}

    def add(key, name):
        index.setdefault(key, set()).add(clean(name))

    for year, session in _SESSION_YEARS.items():
        folder = _LEGISLATOR_DISTRICT / f"{session}th"
        if folder.exists():
            for xlsx in folder.glob("*.xlsx"):
                for row in _rows(xlsx):
                    add((year,) + _district_key(row["region"]), row["name"])
        party = _LEGISLATOR_PARTY / f"{session}th.yaml"
        if party.exists():
            for row in _rows(party):
                add((year, "不分區", 0), row["name"])
        by_dir = _LEGISLATOR_BY_ELECTION / f"{session}th"
        if by_dir.exists():
            for path in by_dir.iterdir():
                if path.suffix.lower() in (".xlsx", ".yaml", ".yml"):
                    for row in _rows(path, by_election=True):
                        region, num = _district_key(row["region"])
                        add((year, "補選", region, num), row["name"])
    return index


def _district_key(region) -> tuple[str, int]:
    """名冊的選舉區寫法各屆不一:「臺北市第01選區」「南投縣 第01選舉區」「嘉義市選舉區」。"""
    text = "".join(str(region).split())
    m = re.match(r"(.+?[市縣])第(\d+)選舉?區", text)
    if m:
        return m.group(1), int(m.group(2))
    if re.fullmatch(r".+?[市縣](選舉區)?", text):
        return re.sub(r"選舉區$", "", text), 1
    return text, 0                      # 平地/山地原住民之類不編號的


_ID = re.compile(r"legislator_(\d{4})_(區域|不分區|原住民|補選)_(.*)")
_SEAT = re.compile(r"第([\d、]+)選舉區")


def expected_names(meta) -> set[str] | None:
    """這場選舉的名冊姓名。沒有名冊可比對時回 None(改用結構分數驗收)。"""
    if meta.type != "legislator":
        return None
    m = _ID.match(meta.election_id)
    if not m:
        return None
    year, category, scope = int(m.group(1)), m.group(2), m.group(3)
    index = _legislator_index()
    scope = scope.split("_")[0]          # 去掉 正面/背面/之N 這種同場分檔的後綴

    if category == "不分區":
        return index.get((year, "不分區", 0)) or None
    if category == "原住民":
        if scope == "平地山地原住民":     # 101 把兩者合刊
            got = (index.get((year, "平地原住民", 0), set())
                   | index.get((year, "山地原住民", 0), set()))
            return got or None
        return index.get((year, scope, 0)) or None

    seat = _SEAT.search(scope)
    region = scope[:seat.start()] if seat else scope
    nums = [int(n) for n in seat.group(1).split("、")] if seat else [1]
    prefix = (year, "補選") if category == "補選" else (year,)
    got: set[str] = set()
    for n in nums:
        got |= index.get(prefix + (region, n), set())
        if category == "補選":           # 補選名冊有些屆次只寫縣市不寫選舉區
            got |= index.get((year, "補選", region, 0), set())
    return got or None
