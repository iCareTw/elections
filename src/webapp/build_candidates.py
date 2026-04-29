from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.validate import validate_candidates
from src.webapp.store import Store


def _candidate_sort_key(c: dict[str, Any]) -> tuple:
    bd = c.get("birthday")
    bkey = (0, 0) if bd is None else (1, -bd.toordinal())
    return (bkey, c.get("name", ""), c.get("id", ""))


def build_candidates_yaml(store: Store) -> list[dict[str, Any]]:
    candidates = store.list_candidates_with_elections()
    for candidate in candidates:
        candidate["elections"].sort(key=lambda e: e["year"])
    return sorted(candidates, key=_candidate_sort_key)


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
