from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.validate import validate_candidates
from src.webapp.store import Store


_ELECTION_KEYS = ("year", "type", "region", "party", "elected", "session", "ticket", "order_id")


def _candidate_birthday(row: dict[str, Any]) -> int | None:
    birthday = row.get("birthday")
    if birthday is None:
        return None
    return int(str(birthday)[:4])


def _build_election(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in _ELECTION_KEYS if key in payload}


def build_candidates_yaml(store: Store) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in store.iter_resolved_records():
        candidate_id = row["candidate_id"]
        payload = row["payload"]
        candidate = grouped.setdefault(
            candidate_id,
            {
                "name": row["name"],
                "id": candidate_id,
                "birthday": _candidate_birthday(row),
                "elections": [],
            },
        )
        election = _build_election(payload)
        if election not in candidate["elections"]:
            candidate["elections"].append(election)

    candidates = list(grouped.values())
    for candidate in candidates:
        candidate["elections"].sort(key=lambda election: election["year"])
    return sorted(candidates, key=lambda candidate: (candidate["elections"][0]["year"], candidate["id"]))


def _load_valid_types(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as f:
        return {row["id"] for row in yaml.safe_load(f) or []}


def write_candidates_yaml(store: Store, output_path: Path, election_types_path: Path) -> list[dict[str, Any]]:
    candidates = build_candidates_yaml(store)
    errors = validate_candidates(candidates, _load_valid_types(election_types_path))
    if errors:
        raise ValueError("; ".join(errors))

    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(candidates, f, allow_unicode=True, sort_keys=False)
    return candidates
