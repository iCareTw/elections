from __future__ import annotations

from typing import Any

from src.normalize import generate_id, normalize_name


def classify_record(record: dict[str, Any], existing: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_name = normalize_name(record["name"])
    matches = [candidate for candidate in existing if normalize_name(candidate["name"]) == normalized_name]

    if not matches:
        return {"kind": "new", "candidate_id": generate_id(record["name"], record.get("birthday"))}

    birthday = record.get("birthday")
    same_birthday = [candidate for candidate in matches if candidate.get("birthday") == birthday]
    if birthday is not None and len(same_birthday) == 1:
        return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}

    return {"kind": "manual", "matches": matches}
