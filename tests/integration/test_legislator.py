"""Integration test: candidates.yaml 立法委員資料 vs _data/legislator/ xlsx 原始資料。"""

import yaml
import pytest
from pathlib import Path

from src.normalize import normalize_name
from src.parse_legislator import parse_file

CANDIDATES_YAML = Path("candidates.yaml")
LEGISLATOR_DIR = Path("_data/legislator")
ELECTION_TYPE = "立法委員"


def _available_sessions() -> list[int]:
    return sorted(
        int(p.name.replace("th", ""))
        for p in LEGISLATOR_DIR.iterdir()
        if p.is_dir() and p.name.endswith("th")
    )


def _parse_xlsx_session(session: int) -> list[dict]:
    """解析該屆所有 xlsx，以 (normalized_name, region) 為 key 回傳 dict。"""
    session_dir = LEGISLATOR_DIR / f"{session}th"
    records = {}
    for xlsx in sorted(session_dir.glob("*.xlsx")):
        for r in parse_file(xlsx):
            key = (normalize_name(r["name"]), r["region"])
            records[key] = {**r, "name": normalize_name(r["name"])}
    return records


def _load_yaml_entries() -> list[dict]:
    """從 candidates.yaml 取出所有立法委員參選紀錄。"""
    with open(CANDIDATES_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    entries = []
    for candidate in data:
        for election in candidate.get("elections", []):
            if election["type"] == ELECTION_TYPE:
                entries.append({
                    "name": normalize_name(candidate["name"]),
                    "birthday": candidate.get("birthday"),
                    "session": election.get("session"),
                    "year": election["year"],
                    "region": election.get("region"),
                    "party": election["party"],
                    "elected": election["elected"],
                })
    return entries


def _get_yaml_sessions() -> list[int]:
    return sorted({e["session"] for e in _load_yaml_entries() if e["session"]})


@pytest.mark.parametrize("session", _available_sessions())
def test_legislator_candidates_match_xlsx(session: int) -> None:
    xlsx = _parse_xlsx_session(session)
    yaml_entries = {
        (e["name"], e["region"]): e
        for e in _load_yaml_entries()
        if e["session"] == session
    }

    xlsx_keys = set(xlsx.keys())
    yaml_keys = set(yaml_entries.keys())

    if not yaml_keys:
        pytest.skip(f"第{session}屆尚未匯入")

    assert yaml_keys == xlsx_keys, (
        f"第{session}屆立法委員資料不完整\n"
        f"  xlsx 筆數: {len(xlsx_keys)}\n"
        f"  yaml 筆數: {len(yaml_keys)}\n"
        f"  缺漏（前10筆）: {sorted(xlsx_keys - yaml_keys)[:10]}"
    )

    for key, x in xlsx.items():
        if key not in yaml_entries:
            continue
        y = yaml_entries[key]
        name, region = key
        assert x["party"] == y["party"], (
            f"第{session}屆 {name} ({region}): 政黨不符 xlsx={x['party']!r} yaml={y['party']!r}"
        )
        assert x["elected"] == y["elected"], (
            f"第{session}屆 {name} ({region}): 當選不符 xlsx={x['elected']} yaml={y['elected']}"
        )
        if x["birthday"] and y["birthday"]:
            assert x["birthday"] == y["birthday"], (
                f"第{session}屆 {name} ({region}): 生年不符 xlsx={x['birthday']} yaml={y['birthday']}"
            )
