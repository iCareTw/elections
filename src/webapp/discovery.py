from __future__ import annotations

import re
from pathlib import Path

import yaml

from src import parse_legislator, parse_mayor, parse_president
from src.session_years import SESSION_YEARS

_SESSION_RE = re.compile(r"(\d+)th")


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


def _discover_president(root: Path) -> list[dict]:
    data_dir = root / "_data" / "president"
    if not data_dir.exists():
        return []
    elections = []
    for path in sorted(data_dir.glob("*.xlsx")):
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
    for path in sorted(data_dir.glob("*.xlsx")):
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
    data_dir = root / "_data" / "legislator" / "district-legislator"
    if not data_dir.exists():
        return []

    elections = []
    for session_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        session = _session_from_text(session_dir.name)
        year = SESSION_YEARS.get(session) if session is not None else None
        for path in sorted(session_dir.glob("*.xlsx")):
            elections.append(
                _record(
                    type_="legislator",
                    election_id=f"legislator/district-legislator/{session_dir.name}/{path.name}",
                    path=path,
                    year=year,
                    session=session,
                )
            )
    return elections


def _discover_party_list(root: Path) -> list[dict]:
    elections = []
    for path in sorted(root.glob("*th.yaml")):
        session = _session_from_text(path.stem)
        year = SESSION_YEARS.get(session) if session is not None else None
        elections.append(
            _record(
                type_="party-list",
                election_id=f"party-list/{path.name}",
                path=path,
                year=year,
                session=session,
            )
        )
    return elections


def discover_elections(root: Path) -> list[dict]:
    elections = []
    elections.extend(_discover_party_list(root))
    elections.extend(_discover_president(root))
    elections.extend(_discover_mayor(root))
    elections.extend(_discover_legislator_district(root))
    return sorted(elections, key=lambda election: election["election_id"])


def _resolve_parser(election: dict):
    election_type = election["type"]
    if election_type == "party-list":
        return _parse_party_list
    if election_type == "president":
        return parse_president.parse_file
    if election_type == "mayor":
        return parse_mayor.parse_file
    if election_type == "legislator":
        return parse_legislator.parse_file
    raise ValueError(f"Unsupported election type: {election_type}")


def _parse_party_list(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_election_records(election: dict) -> list[dict]:
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
