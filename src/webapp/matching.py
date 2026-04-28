from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.normalize import generate_id

if TYPE_CHECKING:
    from src.webapp.store import Store


def classify_record(record: dict[str, Any], store: Store) -> dict[str, Any]:
    matches = store.list_candidates_by_name(record["name"])
    if not matches:
        return {"kind": "new", "candidate_id": generate_id(record["name"], record.get("birthday"))}

    birthday = record.get("birthday")
    same_birthday = [c for c in matches if c.get("birthday") == birthday]
    if birthday is not None and len(same_birthday) == 1:
        return {"kind": "auto", "candidate_id": same_birthday[0]["id"]}

    return {"kind": "manual", "matches": matches}
