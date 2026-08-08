"""不分區公報:一個政黨一組,成員是名單上第 1..N 名。

兩種版面各測一份:113 一個政黨一張小表格(排成兩直欄),
101 一整頁是一張大表格、實際是三直欄的報紙式排版。
"""
from pathlib import Path

import pytest

from src.voter_guide import party_list_parse

ROOT = Path(__file__).resolve().parents[2]
PDF_113 = ROOT / "_data/voter_guide/legislator/11th_113/05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf"
PDF_101 = ROOT / "_data/voter_guide/legislator/08th_101/party/101年全國不分區及僑居國外國民立委選舉.pdf"


def _parse(pdf: Path):
    if not pdf.exists():
        pytest.skip(f"local gazette fixture not available: {pdf.name}")
    return party_list_parse.parse(str(pdf))


def _party(group) -> str:
    return "".join((group.party_cell.text if group.party_cell else "").split())


def test_113_lists_every_party_in_ticket_order():
    groups = _parse(PDF_113)
    assert [g.ticket for g in groups] == list(range(1, 17))


def test_113_long_list_continues_across_pages():
    # 民進黨名單 34 人,從第一頁右欄接到第二頁左欄;接續的表格沒有欄名
    groups = _parse(PDF_113)
    dpp = next(g for g in groups if _party(g) == "民主進步黨")
    assert [m.role for m in dpp.members] == [f"第{n}名" for n in range(1, 35)]


def test_113_candidate_carries_merged_basic_cell_and_platform_on_group():
    groups = _parse(PDF_113)
    first = groups[0]
    assert first.members[0].basic_cell is not None       # 出生年月日/性別/出生地 疊在一格
    assert "政見" in first.members[0].cells              # 政見是政黨的,掛在第一位身上
    assert "學歷" in first.members[0].cells


def test_101_three_column_layout():
    groups = _parse(PDF_101)
    assert [g.ticket for g in groups] == list(range(1, 12))
    kmt = next(g for g in groups if _party(g) == "中國國民黨")
    assert len(kmt.members) == 34
    assert kmt.members[0].cells["出生年月日"].text.strip()
