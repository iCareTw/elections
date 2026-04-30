"""Integration test: candidates.yaml 立法委員資料 vs 原始資料。

區域立委 — 來源：_data/legislator/district-legislator/{session}th/*.xlsx
不分區立委 — 來源：_data/legislator/party-list-legislator/{session}th.yaml
"""

import yaml
import pytest
from pathlib import Path

from src.normalize import normalize_name
from src.parse_legislator import parse_file

CANDIDATES_YAML = Path("candidates.yaml")
LEGISLATOR_DIR = Path("_data/legislator/district-legislator")
PARTY_LIST_DIR = Path("_data/legislator/party-list-legislator")
ELECTION_TYPE = "立法委員"


def _available_sessions() -> list[int]:
    if not LEGISLATOR_DIR.exists():
        return []
    return sorted(
        int(p.name.replace("th", ""))
        for p in LEGISLATOR_DIR.iterdir()
        if p.is_dir() and p.name.endswith("th")
    )


def _available_party_list_sessions() -> list[int]:
    if not PARTY_LIST_DIR.exists():
        return []
    return sorted(
        int(p.stem.replace("th", ""))
        for p in PARTY_LIST_DIR.glob("*th.yaml")
        if p.stem.replace("th", "").isdigit()
    )


def _parse_xlsx_session(session: int) -> dict:
    """解析該屆所有 xlsx，以 (normalized_name, region) 為 key 回傳 dict。"""
    session_dir = LEGISLATOR_DIR / f"{session}th"
    records: dict[tuple, list[dict]] = {}
    for xlsx in sorted(session_dir.glob("*.xlsx")):
        for r in parse_file(xlsx):
            key = (normalize_name(r["name"]), r["region"])
            records.setdefault(key, []).append({**r, "name": normalize_name(r["name"])})
    return records


def _load_yaml_entries() -> list[dict]:
    """從 candidates.yaml 取出所有立法委員參選紀錄。"""
    if not CANDIDATES_YAML.exists():
        return []
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
                    "order_id": election.get("order_id"),
                })
    return entries


# ── 區域立委測試 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("session", _available_sessions())
def test_district_legislator_candidates_match_xlsx(session: int) -> None:
    """區域立委：candidates.yaml 的非全國選區筆數需與 xlsx 完全吻合。"""
    xlsx = _parse_xlsx_session(session)

    yaml_entries: dict[tuple, list[dict]] = {}
    for e in _load_yaml_entries():
        if e["session"] == session and e["region"] != "全國":
            yaml_entries.setdefault((e["name"], e["region"]), []).append(e)

    xlsx_keys = set(xlsx.keys())
    yaml_keys = set(yaml_entries.keys())

    if not yaml_keys:
        pytest.skip(f"第{session}屆區域立委尚未匯入")

    assert yaml_keys == xlsx_keys, (
        f"第{session}屆區域立委資料不完整\n"
        f"  xlsx 筆數: {len(xlsx_keys)}\n"
        f"  yaml 筆數: {len(yaml_keys)}\n"
        f"  缺漏（前10筆）: {sorted(xlsx_keys - yaml_keys)[:10]}"
    )

    # xlsx 生年有誤，經人工確認後略過比對
    birthday_skip = {
        ("徐能安", "新竹縣選舉區"),
        ("吳光訓", "高雄縣選舉區"),
        ("林志隆", "高雄縣選舉區"),
        ("葉宜津", "臺南縣選舉區"),
        ("林建榮", "宜蘭縣選舉區"),
    }

    for key, x_list in xlsx.items():
        if key not in yaml_entries:
            continue
        y_list = yaml_entries[key]
        name, region = key
        for x in x_list:
            y = next((e for e in y_list if e["birthday"] == x["birthday"]), None)
            if y is None and len(y_list) == 1:
                y = y_list[0]
            if y is None:
                continue
            assert x["party"] == y["party"], (
                f"第{session}屆 {name} ({region}): 政黨不符 xlsx={x['party']!r} yaml={y['party']!r}"
            )
            assert x["elected"] == y["elected"], (
                f"第{session}屆 {name} ({region}): 當選不符 xlsx={x['elected']} yaml={y['elected']}"
            )
            if x["birthday"] and y["birthday"] and (name, region) not in birthday_skip:
                assert x["birthday"] == y["birthday"], (
                    f"第{session}屆 {name} ({region}): 生年不符 xlsx={x['birthday']} yaml={y['birthday']}"
                )


# ── 不分區立委測試 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("session", _available_party_list_sessions())
def test_party_list_candidates_match_yaml(session: int) -> None:
    """不分區立委：party-list yaml 裡每一筆都應出現在 candidates.yaml 的 region='全國' 選舉中。"""
    source_path = PARTY_LIST_DIR / f"{session}th.yaml"
    with source_path.open(encoding="utf-8") as f:
        source = yaml.safe_load(f) or []

    # 以 (normalized_name, party, order_id) 建立來源 set
    source_keys = {
        (normalize_name(r["name"]), r["party"], r.get("order_id"))
        for r in source
    }

    yaml_keys = {
        (e["name"], e["party"], e["order_id"])
        for e in _load_yaml_entries()
        if e["session"] == session and e["region"] == "全國"
    }

    if not yaml_keys:
        pytest.skip(f"第{session}屆不分區立委尚未匯入")

    missing = source_keys - yaml_keys
    assert not missing, (
        f"第{session}屆不分區立委缺漏 {len(missing)} 筆（前10）：\n"
        + "\n".join(f"  {m}" for m in sorted(missing)[:10])
    )
