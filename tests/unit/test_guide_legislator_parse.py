"""區域立委公報解析的三個回歸點(都曾整份讀不到候選人)。"""
from pathlib import Path

import pytest

from src.voter_guide import table_parse

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "_data/voter_guide/legislator"
ROLE = "立法委員"


def _parse(rel: str):
    pdf = BASE / rel
    if not pdf.exists():
        pytest.skip(f"local gazette fixture not available: {pdf.name}")
    return table_parse.parse(str(pdf), role=ROLE)


def _names(groups):
    return ["".join(m.cells["姓名"].text.split())
            for g in groups for m in g.members if "姓名" in m.cells]


def test_section_heading_with_district_is_kept():
    # 「第1選舉區」出現在段落標題裡:縣市長那套規則會把整份濾光
    groups = _parse("08th_101/district/01臺北市/臺北市立委選舉第1選區.pdf")
    assert "丁守中" in _names(groups)


def test_113_vertical_layout_with_glued_labels():
    # 113 一位候選人一張小表格,欄名前黏著段落標題的碎字(『舉區（北投區·號次姓名』),
    # 個人資料的合併格叫「基本資料」而非縣市長的「個人資料」
    groups = _parse("11th_113/02區域立法委員/02臺北市/第1選舉區/臺北市立委第1選舉區.pdf")
    assert len(groups) == 8
    first = groups[0].members[0]
    assert "".join(first.cells["姓名"].text.split()) == "吳思瑤"
    assert first.basic_cell is not None
    assert "政見" in first.cells          # 格內抽不到文字,但位置要留給看圖


def test_broken_pdf_index_is_repaired_on_open():
    # 109 臺北市八個選舉區的 PDF 索引表壞掉,pdfplumber 直接打不開
    groups = _parse("10th_109/02區域立法委員/02臺北市/臺北市立委第1選舉區.pdf")
    assert "吳思瑤" in _names(groups)
