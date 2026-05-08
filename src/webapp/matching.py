from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.normalize import generate_id, normalize_candidate_name, normalize_name_without_latin

if TYPE_CHECKING:
    from src.webapp.store import Store


def classify_record_cached(
    record: dict[str, Any],
    candidates_by_name: dict[str, list[dict[str, Any]]],
    all_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """classify_record using pre-fetched candidate data — no DB calls."""
    normalized = normalize_candidate_name(record["name"])
    matches = candidates_by_name.get(normalized, [])

    if not matches:
        normalized_wl = normalize_name_without_latin(record["name"])
        fallback = (
            [c for c in all_candidates if normalize_name_without_latin(c["name"]) == normalized_wl]
            if normalized_wl else []
        )
        birthday = record.get("birthday")
        same_birthday = [c for c in fallback if c.get("birthday") == birthday]
        if birthday is not None and len(same_birthday) == 1:
            return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}
        return {"kind": "new", "candidate_id": generate_id(record["name"], record.get("birthday"))}

    birthday = record.get("birthday")
    same_birthday = [c for c in matches if c.get("birthday") == birthday]
    if birthday is not None and len(same_birthday) == 1:
        return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}

    return {"kind": "manual", "matches": matches}


def classify_record(record: dict[str, Any], store: Store) -> dict[str, Any]:
    matches = store.list_candidates_by_name(record["name"])
    if not matches:
        fallback_matches = store.list_candidates_by_name_without_latin(record["name"])
        birthday = record.get("birthday")
        same_birthday = [c for c in fallback_matches if c.get("birthday") == birthday]
        if birthday is not None and len(same_birthday) == 1:
            return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}
        return {"kind": "new", "candidate_id": generate_id(record["name"], record.get("birthday"))}

    birthday = record.get("birthday")
    same_birthday = [c for c in matches if c.get("birthday") == birthday]
    if birthday is not None and len(same_birthday) == 1:
        return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}

    return {"kind": "manual", "matches": matches}
