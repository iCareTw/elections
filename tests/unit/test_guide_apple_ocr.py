from pathlib import Path

import pytest

from src.voter_guide import apple_ocr
from src.voter_guide.pipeline import SOURCE_OCR, SOURCE_TEXT, _parse_structure, parse_pdf

ROOT = Path(__file__).resolve().parents[2]
PDF_105 = ROOT / "_data/voter_guide/president/105年第14任總統副總統.pdf"
PDF_113 = ROOT / "_data/voter_guide/president/113年第16任總統副總統.pdf"


# ---- 字塊修補(純邏輯,不需 macOS) ----

def test_repair_runs_merges_split_glyph():
    # 『黨』下半的灬被投影切成獨立小塊 → 併回上半(間隙 1px)
    runs = [(0, 88), (100, 186), (200, 273), (274, 288), (300, 388)]
    assert apple_ocr._repair_runs(runs) == [(0, 88), (100, 186), (200, 288), (300, 388)]


def test_repair_runs_merges_toward_nearer_side():
    # 『7』的橫筆離下方字身近、離上方『月』遠 → 應往下併,不可併進『月』
    runs = [(0, 61), (75, 147), (160, 177), (180, 220), (240, 307)]
    assert apple_ocr._repair_runs(runs) == [(0, 61), (75, 147), (160, 220), (240, 307)]


def test_repair_runs_drops_border_remnant():
    # 尾端 7px 框線殘影孤立(間隙大,併不進來) → 丟掉,否則會被讀成『一』
    runs = [(0, 61), (75, 147), (160, 221), (600, 607)]
    assert apple_ocr._repair_runs(runs) == [(0, 61), (75, 147), (160, 221)]


def test_repair_runs_keeps_single_glyph():
    assert apple_ocr._repair_runs([(10, 120)]) == [(10, 120)]


# ---- 105 公報(文字轉向量曲線,幾何抽不到字)實際解析 ----

@pytest.fixture(scope="module")
def groups_105():
    if not PDF_105.exists():
        pytest.skip("local 105 president PDF fixture not available")
    if not apple_ocr.available():
        pytest.skip("macOS Vision OCR not available")
    return apple_ocr.parse(PDF_105)


def test_parse_105_finds_three_tickets(groups_105):
    assert [g.ticket for g in groups_105] == [1, 2, 3]
    for g in groups_105:
        assert g.president and g.vice


def test_parse_105_reads_vertical_fields(groups_105):
    # 直排欄位:整格讀會空,需切字重排
    names = [(g.president.cells["姓名"].text, g.vice.cells["姓名"].text)
             for g in groups_105]
    assert names == [("朱立倫", "王如玄"), ("蔡英文", "陳建仁"), ("宋楚瑜", "徐欣瑩")]

    dates = [g.president.cells["出生年月日"].text for g in groups_105]
    assert dates == ["50年6月7日", "45年8月31日", "31年3月16日"]

    # 登記方式的『黨』字最易被切壞(讀成『堂』+『灬』)
    parties = [g.president.cells["登記方式"].text for g in groups_105]
    assert parties == ["中國國民黨推薦", "民主進步黨推薦", "親民黨推薦"]


def test_parse_105_reads_horizontal_fields(groups_105):
    """橫排長欄位逐字比對公報原文(條列欄位保留換行,接起來才是原文)。"""
    p = groups_105[0].president
    assert p.cells["住址"].text == "新北市三重區富貴里32鄰三信路130號13樓"
    assert p.cells["經歷"].text.replace("\n", "") == (
        "國民黨主席、第1屆、第2屆新北市長、行政院副院長、桃園縣第14屆、第15屆縣長、"
        "第4屆立法委員、國立臺灣大學教授、美國紐約市立大學助理教授")
    assert p.cells["學歷"].text.replace("\n", "") == (
        "美國紐約大學會計學博士美國紐約大學財務金融學碩士臺灣大學工商管理學士")


def test_parse_105_assigns_photos(groups_105):
    for g in groups_105:
        assert g.president.photo_bbox and g.vice.photo_bbox


# ---- A 路來源自動判斷 ----

def test_structure_source_falls_back_to_ocr():
    if not PDF_105.exists():
        pytest.skip("local 105 president PDF fixture not available")
    if not apple_ocr.available():
        pytest.skip("macOS Vision OCR not available")
    groups, source = _parse_structure(str(PDF_105))
    assert source == SOURCE_OCR
    assert len(groups) == 3


def test_structure_source_prefers_pdf_text():
    if not PDF_113.exists():
        pytest.skip("local 113 president PDF fixture not available")
    # 113 抽得到內嵌文字 → 不該退到 OCR(慢且無必要)
    groups, source = _parse_structure(str(PDF_113))
    assert source == SOURCE_TEXT
    assert groups


def test_parse_pdf_105_bullets_come_from_ocr(tmp_path):
    """學歷/經歷用 OCR 原文切條目(不採模型排版,模型會改壞字)。"""
    if not PDF_105.exists():
        pytest.skip("local 105 president PDF fixture not available")
    if not apple_ocr.available():
        pytest.skip("macOS Vision OCR not available")
    result, _ = parse_pdf(str(PDF_105), "105", tmp_path, use_vision=False)
    tsai = result[1]["總統"]
    assert tsai["姓名"] == "蔡英文"
    assert tsai["學歷"] == "- 倫敦政經學院法學博士\n- 國立台灣大學法律系學士"
    assert tsai["經歷"].startswith("- 民主進步黨黨主席\n- 行政院副院長\n")
    # 一行一條目的學歷:行內『、』不可切開
    assert "- 國立交通大學土木系碩士、博士" in result[2]["副總統"]["學歷"]


def test_parse_pdf_105_without_vision(tmp_path):
    """整條流程(不打模型):號次、政黨、相片都要出來。"""
    if not PDF_105.exists():
        pytest.skip("local 105 president PDF fixture not available")
    if not apple_ocr.available():
        pytest.skip("macOS Vision OCR not available")
    result, _ = parse_pdf(str(PDF_105), "105", tmp_path, use_vision=False)
    assert [e["號次"] for e in result] == [1, 2, 3]
    assert [e["政黨"] for e in result] == ["中國國民黨", "民主進步黨", "親民黨"]
    assert result[0]["總統"]["姓名"] == "朱立倫"
    assert result[0]["總統"]["出生年月日"] == "民國50年6月7日"
    assert Path(result[0]["總統"]["相片"]).exists()
