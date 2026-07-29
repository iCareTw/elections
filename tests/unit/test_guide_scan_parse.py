"""掃描圖公報解析(scan_grid / layout / scan_parse)。

純邏輯部分不需 macOS;實際解析需要 Vision OCR 與本地 PDF,缺任一就 skip。
"""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from src.voter_guide import apple_ocr, scan_grid, scan_parse
from src.voter_guide.pipeline import SOURCE_SCAN, _parse_structure

ROOT = Path(__file__).resolve().parents[2]
GUIDE_DIR = ROOT / "_data/voter_guide/president"

SCANS = {
    "085年第9任總統副總統.pdf": 4,
    "089年第10任總統副總統.pdf": 5,
    "093年第11任總統副總統.pdf": 2,
    "097年第12任總統副總統.pdf": 2,
}


# ---- 直書右到左的字序還原 ----

def test_reverse_vertical_chinese():
    assert scan_parse.reverse_vertical("扁水陳") == "陳水扁"
    assert scan_parse.reverse_vertical("薦推黨民親") == "親民黨推薦"


def test_reverse_vertical_keeps_multi_digit_numbers():
    # 數字本身是橫排的,不能跟著倒(否則 40→04、18→81)
    assert scan_parse.reverse_vertical("日81月2年04") == "04年2月81日"
    assert scan_parse.reverse_vertical("日18月2年40") == "40年2月18日"


def test_reverse_vertical_address_with_numbers():
    assert (scan_parse.reverse_vertical("號120段三路愛仁市北台")
            == "台北市仁愛路三段120號")


# ---- 兩種讀法擇優 ----

def test_pick_reading_prefers_fewer_letters_between_chinese():
    # 網點誤判會在中文之間塞進字母
    assert scan_parse._pick_reading("陳K扁", "陳水扁") == "陳水扁"


def test_pick_reading_prefers_more_complete_when_equally_clean():
    assert scan_parse._pick_reading("李登", "李登輝") == "李登輝"
    assert scan_parse._pick_reading("41年1月日", "41年1月1日") == "41年1月1日"


def test_noise_score_ignores_digits():
    # 日期的數字夾在年月日之間,不該被當成雜訊
    assert scan_parse._noise_score("35年5月18日") == 0
    assert scan_parse._noise_score("陳K扁") == 1


# ---- 格線工具 ----

def _ruled_image(xs, width=400, height=200, bg="white", ink="black"):
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    for x in xs:
        draw.line([(x, 0), (x, height)], fill=ink, width=2)
    return img


def test_find_rules_locates_drawn_lines():
    img = _ruled_image([50, 150, 250, 350])
    found = scan_grid.find_rules(scan_grid.ink_profile(img, "x", 128))
    assert [abs(f - e) <= 2 for f, e in zip(found, [50, 150, 250, 350])] == [True] * 4


def test_find_rules_ignores_wide_ink_bands():
    """直排文字整欄都是墨,寬度遠超格線 → 不可當成線。"""
    img = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(img).rectangle([100, 0, 160, 200], fill="black")
    assert scan_grid.find_rules(scan_grid.ink_profile(img, "x", 128)) == []


def test_auto_threshold_follows_background():
    """085 是淺藍印刷,固定門檻會整份抓不到線。"""
    pale = Image.new("RGB", (50, 50), (255, 255, 255))
    assert scan_grid.auto_threshold(pale) > 200
    dark = Image.new("RGB", (50, 50), (120, 120, 120))
    assert scan_grid.auto_threshold(dark) < 200


def test_even_runs_picks_equally_spaced_series():
    # 候選人欄一定等寬;10/137 是版面雜訊,1180 離預測的 1100 太遠
    marks = [10, 137, 300, 500, 700, 900, 1180]
    assert scan_grid.even_runs(marks) == [300, 500, 700, 900]


def test_even_runs_does_not_bridge_gaps():
    # 中間缺一條就該停,不可跨過缺口硬接成假等距
    assert scan_grid.even_runs([100, 200, 300, 900, 1000]) == [100, 200, 300]


# ---- 實際公報 ----

def _skip_unless_ready(pdf: Path):
    if not pdf.exists():
        pytest.skip(f"local fixture not available: {pdf.name}")
    if not apple_ocr.available():
        pytest.skip("macOS Vision OCR not available")


@pytest.mark.parametrize("filename,expected", SCANS.items())
def test_scanned_bulletins_yield_expected_groups(filename, expected):
    pdf = GUIDE_DIR / filename
    _skip_unless_ready(pdf)
    groups = scan_parse.parse(str(pdf))
    assert len(groups) == expected
    for g in groups:
        assert g.president is not None and g.vice is not None
        assert g.president.role == "總統" and g.vice.role == "副總統"


def test_right_to_left_bulletin_reads_names_in_order():
    """093 是直書右到左:第 1 組必須是最右邊那組,字序也要還原。"""
    pdf = GUIDE_DIR / "093年第11任總統副總統.pdf"
    _skip_unless_ready(pdf)
    groups = scan_parse.parse(str(pdf))
    assert [g.president.cells["姓名"].text for g in groups] == ["陳水扁", "連戰"]
    assert groups[0].vice.cells["姓名"].text == "呂秀蓮"


def test_merged_registration_cell_read_whole():
    """登記方式是正副共用的合併格,分開讀會各拿到半句。"""
    pdf = GUIDE_DIR / "093年第11任總統副總統.pdf"
    _skip_unless_ready(pdf)
    groups = scan_parse.parse(str(pdf))
    assert groups[0].president.cells["登記方式"].text == "民主進步黨推薦"


def test_scanned_bulletin_routes_to_scan_source():
    pdf = GUIDE_DIR / "097年第12任總統副總統.pdf"
    _skip_unless_ready(pdf)
    groups, source = _parse_structure(str(pdf))
    assert source == SOURCE_SCAN
    assert len(groups) == 2
