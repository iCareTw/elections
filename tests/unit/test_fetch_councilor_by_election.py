from pathlib import Path

import pytest

from src.fetch_councilor_by_election import _birthyear, _votes, election_name, output_path


def test_election_name_drops_the_announcement_suffix() -> None:
    assert election_name("花蓮縣議會第19屆議員選舉第8選舉區缺額補選結果") == (
        "花蓮縣議會第19屆議員選舉第8選舉區缺額補選"
    )


def test_election_name_keeps_names_without_the_suffix() -> None:
    assert election_name("澎湖縣議會第19屆議員第3選舉區缺額補選") == "澎湖縣議會第19屆議員第3選舉區缺額補選"


def test_output_path_groups_by_vote_year() -> None:
    assert output_path(2020, "新竹縣議會第19屆議員第4選舉區缺額補選") == Path(
        "_data/council/2020/新竹縣議會第19屆議員第4選舉區缺額補選.xlsx"
    )


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("060/03/28", 1971),
        ("45 年 4 月 9 日", 1956),
        ("46.2.2", 1957),
        ("74/02/04", 1985),
        ("", None),
    ],
)
def test_birthyear_converts_roc_year_regardless_of_notation(cell: str, expected: int | None) -> None:
    assert _birthyear(cell) == expected


def test_votes_strips_thousand_separators() -> None:
    assert _votes("3,587") == 3587
    assert _votes("") == 0
