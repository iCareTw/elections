from src.normalize import normalize_name
from src.webapp.matching import classify_record


class _FakeStore:
    """Minimal Store stub that serves a fixed candidates list."""

    def __init__(self, candidates: list[dict]) -> None:
        self._candidates = candidates

    def list_candidates_by_name(self, name: str) -> list[dict]:
        normalized = normalize_name(name)
        return [c for c in self._candidates if normalize_name(c["name"]) == normalized]


def test_classify_record_auto_matches_same_name_same_birthday() -> None:
    record = {"name": "柯文哲", "birthday": 1959}
    existing = [{"name": "柯文哲", "birthday": 1959, "id": "id_柯文哲_1959"}]

    result = classify_record(record, _FakeStore(existing))

    assert result == {"kind": "auto", "candidate_id": "id_柯文哲_1959"}


def test_classify_record_manually_matches_same_name_different_birthday() -> None:
    record = {"name": "柯文哲", "birthday": 1959}
    existing = [{"name": "柯文哲", "birthday": 1960, "id": "id_柯文哲_1960"}]

    result = classify_record(record, _FakeStore(existing))

    assert result == {"kind": "manual", "matches": existing}


def test_classify_record_manually_matches_same_name_missing_birthday() -> None:
    record = {"name": "柯文哲", "birthday": None}
    existing = [{"name": "柯文哲", "birthday": 1959, "id": "id_柯文哲_1959"}]

    result = classify_record(record, _FakeStore(existing))

    assert result == {"kind": "manual", "matches": existing}


def test_classify_record_manually_matches_duplicate_same_birthday() -> None:
    record = {"name": "柯文哲", "birthday": 1959}
    existing = [
        {"name": "柯文哲", "birthday": 1959, "id": "id_柯文哲_1959"},
        {"name": "柯 文 哲", "birthday": 1959, "id": "id_柯文哲_duplicate"},
    ]

    result = classify_record(record, _FakeStore(existing))

    assert result == {"kind": "manual", "matches": existing}


def test_classify_record_creates_new_id_without_same_name_match() -> None:
    record = {"name": "黃珊珊", "birthday": 1969}
    existing = [{"name": "柯文哲", "birthday": 1959, "id": "id_柯文哲_1959"}]

    result = classify_record(record, _FakeStore(existing))

    assert result == {"kind": "new", "candidate_id": "id_黃珊珊_1969"}
