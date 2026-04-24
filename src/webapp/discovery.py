from __future__ import annotations

import re
from pathlib import Path

from src.parse_legislator import SESSION_YEARS

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
    root: Path,
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
        "path": path.relative_to(root),
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
                root,
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
                root,
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
                    root,
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
                root,
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
