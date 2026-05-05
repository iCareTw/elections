from __future__ import annotations

import re
from pathlib import Path

import yaml

from src import (
    parse_council,
    parse_legislator,
    parse_legislator_by_election,
    parse_mayor,
    parse_president,
)
from src.session_years import SESSION_YEARS

_SESSION_RE = re.compile(r"(\d+)th")


def natural_sort_key(s: str):
    """Natural sort key to match VSCode behavior (e.g., 4th before 10th)."""
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r"([0-9]+)", str(s))]


def _session_from_text(text: str) -> int | None:
    match = _SESSION_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def _president_year(filename: str) -> int | None:
    match = re.search(r"第(\d+)任", filename)
    if not match:
        return None
    return 1996 + (int(match.group(1)) - 9) * 4


def _mayor_year(filename: str) -> int | None:
    match = re.search(r"(\d+)年", filename)
    if not match:
        return None
    return int(match.group(1)) + 1911


def _record(
    *,
    type_: str,
    election_id: str,
    path: Path,
    year: int | None = None,
    session: int | None = None,
) -> dict:
    record = {
        "election_id": election_id,
        "type": type_,
        "label": path.stem,
        "path": path,
        "status": "todo",
    }
    if year is not None:
        record["year"] = year
    if session is not None:
        record["session"] = session
    return record


def _visible_children(path: Path) -> list[Path]:
    children = [child for child in path.iterdir() if not child.name.startswith("_")]
    return sorted(children, key=lambda p: natural_sort_key(p.name))


def _first_existing_dir(root: Path, *parts_options: str) -> Path | None:
    for part in parts_options:
        candidate = root / "_data" / "legislator" / part
        if candidate.exists():
            return candidate
    return None


def _discover_president(root: Path) -> list[dict]:
    data_dir = root / "_data" / "president"
    if not data_dir.exists():
        return []

    elections = []
    for path in _visible_children(data_dir):
        if path.is_file() and path.suffix.lower() == ".xlsx":
            elections.append(
                _record(
                    type_="president",
                    election_id=f"president/{path.name}",
                    path=path,
                    year=_president_year(path.name),
                )
            )
    return elections


def _discover_mayor(root: Path) -> list[dict]:
    data_dir = root / "_data" / "mayor"
    if not data_dir.exists():
        return []

    elections = []
    for path in _visible_children(data_dir):
        if path.is_file() and path.suffix.lower() == ".xlsx":
            elections.append(
                _record(
                    type_="mayor",
                    election_id=f"mayor/{path.name}",
                    path=path,
                    year=_mayor_year(path.name),
                )
            )
    return elections


def _discover_legislator_district(root: Path) -> list[dict]:
    data_dir = _first_existing_dir(root, "district-legislator", "district")
    if data_dir is None:
        return []

    elections = []
    for session_dir in _visible_children(data_dir):
        if not session_dir.is_dir():
            continue
        session = _session_from_text(session_dir.name)
        year = SESSION_YEARS.get(session) if session is not None else None
        for path in _visible_children(session_dir):
            if path.is_file() and path.suffix.lower() == ".xlsx":
                elections.append(
                    _record(
                        type_="legislator",
                        election_id=f"legislator/{data_dir.name}/{session_dir.name}/{path.name}",
                        path=path,
                        year=year,
                        session=session,
                    )
                )
    return elections


def _discover_legislator_party_list(root: Path) -> list[dict]:
    data_dir = _first_existing_dir(root, "party-list-legislator", "party-list")
    if data_dir is None:
        return []

    elections = []
    for path in _visible_children(data_dir):
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
            session = _session_from_text(path.stem)
            year = SESSION_YEARS.get(session) if session is not None else None
            elections.append(
                _record(
                    type_="party-list",
                    election_id=f"legislator/{data_dir.name}/{path.name}",
                    path=path,
                    year=year,
                    session=session,
                )
            )
    return elections


def _discover_legislator_by_election(root: Path) -> list[dict]:
    data_dir = _first_existing_dir(root, "by-election-legislator")
    if data_dir is None:
        return []

    elections = []
    for child in _visible_children(data_dir):
        if child.is_file() and child.suffix.lower() in {".yaml", ".yml"}:
            session = _session_from_text(child.stem)
            elections.append(
                _record(
                    type_="legislator-by-election",
                    election_id=f"legislator/{data_dir.name}/{child.name}",
                    path=child,
                    session=session,
                )
            )
            continue

        if not child.is_dir():
            continue

        session = _session_from_text(child.name)
        for path in _visible_children(child):
            if path.is_file() and path.suffix.lower() == ".xlsx":
                elections.append(
                    _record(
                        type_="legislator-by-election",
                        election_id=f"legislator/{data_dir.name}/{child.name}/{path.name}",
                        path=path,
                        session=session,
                    )
                )
    return elections


def _discover_council(root: Path) -> list[dict]:
    data_dir = root / "_data" / "council"
    if not data_dir.exists():
        return []

    elections = []
    for year_dir in _visible_children(data_dir):
        if not year_dir.is_dir():
            continue
        try:
            year = int(year_dir.name)
        except ValueError:
            continue
        for path in _visible_children(year_dir):
            if path.is_file() and path.suffix.lower() == ".xlsx":
                elections.append(
                    _record(
                        type_="council",
                        election_id=f"council/{year_dir.name}/{path.name}",
                        path=path,
                        year=year,
                    )
                )
    return elections


def discover_elections(root: Path) -> list[dict]:
    elections = []
    elections.extend(_discover_president(root))
    elections.extend(_discover_mayor(root))
    elections.extend(_discover_legislator_district(root))
    elections.extend(_discover_legislator_party_list(root))
    elections.extend(_discover_legislator_by_election(root))
    elections.extend(_discover_council(root))
    return sorted(elections, key=lambda e: [natural_sort_key(p) for p in e["election_id"].split("/")])


def _resolve_parser(election: dict):
    """
    根據 election 的類型與檔案格式決定要使用哪個 parser 來讀取原始資料.
    邏輯必須寫死中選會揭露的原始資料混亂所導致.
        - president & mayor 是 xlsx, 且歷史資料格式一致
        - legislator 的區域與不分區及 council 資料格式完全不同, 歷屆立委/議員由人工處理以後整理成 yaml
    """
    path = Path(election["path"])
    if path.suffix.lower() in {".yaml", ".yml"}:
        return _parse_yaml_records

    election_type = election["type"]
    if election_type == "president":
        return parse_president.parse_file
    if election_type == "mayor":
        return parse_mayor.parse_file
    if election_type == "legislator":
        return parse_legislator.parse_file
    if election_type == "legislator-by-election":
        return parse_legislator_by_election.parse_file
    if election_type == "council":
        return parse_council.parse_file
    raise ValueError(f"Unsupported election type: {election_type}")


def _parse_yaml_records(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_election_records(election: dict) -> list[dict]:
    """
    依 選舉設定(ex: 11th.yaml) 讀取原始資料, 並補上 election_id 與 source_record_id
    """

    parser = _resolve_parser(election)
    rows = []
    for index, record in enumerate(parser(election["path"])):
        rows.append(
            {
                **record,
                "election_id": election["election_id"],
                "source_record_id": f'{election["election_id"]}:{index}',
            }
        )
    return rows
