"""縣市長公報:選舉身分判定與四種版面的切分。

固定版面各挑一份 2022 公報當樣本。公報在 `_data/`(未進版控),缺檔時跳過。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.voter_guide import election_meta, table_parse

ROOT = Path(__file__).resolve().parents[2]
MAYOR_DIR = ROOT / "_data/voter_guide/mayor/111"


def _names(pdf_name: str) -> list[tuple[int, str]]:
    pdf = MAYOR_DIR / pdf_name
    if not pdf.exists():
        pytest.skip(f"local gazette fixture not available: {pdf_name}")
    meta = election_meta.from_pdf_path(pdf)
    groups = table_parse.parse(pdf, role=meta.roles[0])
    return [(g.ticket, "".join(g.members[0].cells["姓名"].text.split()))
            for g in groups]


def test_meta_from_mayor_path():
    meta = election_meta.from_pdf_path("_data/voter_guide/mayor/111/臺北市市長.pdf")
    assert (meta.type, meta.year, meta.region) == ("mayor", 2022, "臺北市")
    assert meta.election_id == "mayor_2022_臺北市"
    assert meta.roles == ("市長",) and not meta.paired


def test_meta_normalises_tai_and_keeps_rerun_separate():
    """『台南』寫成官方的『臺南』;重行選舉不覆蓋原場次。"""
    tainan = election_meta.from_pdf_path("_data/voter_guide/mayor/111/台南市市長.pdf")
    assert tainan.election_id == "mayor_2022_臺南市"
    rerun = election_meta.from_pdf_path(
        "_data/voter_guide/mayor/111/嘉義市市長重行選舉.pdf")
    assert rerun.election_id == "mayor_2022_嘉義市_重行選舉"


def test_meta_from_president_path_still_paired():
    meta = election_meta.from_pdf_path(
        "_data/voter_guide/president/113年第16任總統副總統.pdf")
    assert meta.election_id == "president_2024_16"
    assert meta.roles == ("總統", "副總統") and meta.paired


def test_recall_notice_is_not_a_gazette():
    """罷免公告不是公報,匯入清單不該列出。"""
    assert not election_meta.is_gazette(
        MAYOR_DIR / "第11屆立法委員(新竹市選舉區)鄭正鈐及新竹市第11屆市長高虹安罷免案罷免公告.pdf")


def test_header_row_layout():
    """版式 H:一列全是欄名,其後每列一位候選人。"""
    assert _names("桃園市市長.pdf") == [
        (1, "張善政"), (2, "賴香伶"), (3, "鄭運鵬"), (4, "鄭寶清")]


def test_inline_label_layout_skips_councillors():
    """版式 I:欄名與值成對相鄰、兩人並排;同一份 PDF 裡的議員候選人要濾掉。"""
    assert _names("新北市市長.pdf") == [(1, "林佳龍"), (2, "侯友宜")]


def test_vertical_label_layout():
    """版式 V:一張表格一位候選人,欄名在上、值在正下方。"""
    got = _names("臺北市市長.pdf")
    assert len(got) == 12
    assert got[0] == (1, "張家豪") and got[-1] == (12, "陳時中")


def test_repeated_header_puts_two_candidates_on_one_row():
    """欄名整組重複 → 同一列並排兩位候選人。"""
    got = _names("新竹市市長.pdf")
    assert [t for t, _ in got] == [1, 2, 3, 4, 5, 6]
    assert dict(got)[6] == "高虹安"


def test_section_marker_inside_table_splits_mayor_from_councillors():
    """臺中把『選舉類別』做成表格首欄,議員候選人與市長在同一張表 → 仍要切得開。"""
    assert _names("臺中市市長.pdf") == [(1, "陳美妃"), (2, "蔡其昌"), (3, "盧秀燕")]


def test_name_split_across_rows_is_one_candidate():
    """直書姓名被列邊界切斷(『李驥』/『羣』)要併回同一位,不能變成多一位候選人。"""
    pdf = ROOT / "_data/voter_guide/mayor/107/新竹市市長.pdf"
    if not pdf.exists():
        pytest.skip("local gazette fixture not available: 107/新竹市市長.pdf")
    meta = election_meta.from_pdf_path(pdf)
    got = [(g.ticket, "".join(g.members[0].cells["姓名"].text.split()))
           for g in table_parse.parse(pdf, role=meta.roles[0])]
    assert got == [(1, "謝文進"), (2, "李驥羣"), (3, "黃源甫"),
                   (4, "許明財"), (5, "郭榮睿"), (6, "林智堅")]


def test_ticket_restart_ends_the_election():
    """議員段落的標題是直排美術字、抽不出文字時,靠「號次退回 1」收尾。

    2018 臺北市長只有 5 位,其後接的是議員(號次從 1 重新編)。
    """
    pdf = ROOT / "_data/voter_guide/mayor/107/臺北市市長.pdf"
    if not pdf.exists():
        pytest.skip("local gazette fixture not available: 107/臺北市市長.pdf")
    meta = election_meta.from_pdf_path(pdf)
    got = [(g.ticket, "".join(g.members[0].cells["姓名"].text.split()))
           for g in table_parse.parse(pdf, role=meta.roles[0])]
    assert got == [(1, "吳蕚洋"), (2, "丁守中"), (3, "姚文智"),
                   (4, "柯文哲"), (5, "李錫錕")]


def test_full_width_banner_ends_the_election():
    """橫跨整表的橫幅(『縣議員第一選區(花蓮市)』)也是換一場選舉的宣告。"""
    pdf = ROOT / "_data/voter_guide/mayor/107/花蓮縣縣長議員選舉公報.pdf"
    if not pdf.exists():
        pytest.skip("local gazette fixture not available")
    meta = election_meta.from_pdf_path(pdf)
    got = [(g.ticket, "".join(g.members[0].cells["姓名"].text.split()))
           for g in table_parse.parse(pdf, role=meta.roles[0])]
    assert got == [(1, "徐榛蔚"), (2, "劉曉玫"), (3, "黄師鵬")]


def test_anchor_found_when_label_is_glued_to_other_text():
    """欄名後面黏著別的字(『號次2經歷』)時仍要認得出候選人卡片,否則會少一位。"""
    pdf = ROOT / "_data/voter_guide/mayor/107/新北市市長.pdf"
    if not pdf.exists():
        pytest.skip("local gazette fixture not available")
    meta = election_meta.from_pdf_path(pdf)
    got = [(g.ticket, "".join(g.members[0].cells["姓名"].text.split()))
           for g in table_parse.parse(pdf, role=meta.roles[0])]
    assert got == [(1, "蘇貞昌"), (2, "侯友宜")]


def test_region_read_from_gazette_title_when_filename_is_useless():
    """檔名看不出縣市時改讀公報抬頭;內文提到的別的縣市不能蓋過抬頭。"""
    pdf = ROOT / "_data/voter_guide/mayor/107/第18屆縣長候選人選舉公報.pdf"
    if not pdf.exists():
        pytest.skip("local gazette fixture not available")
    assert election_meta.from_pdf_path(pdf).election_id == "mayor_2018_雲林縣"


def test_split_label_rows_are_merged():
    """金門的欄名被列邊界切成上下兩段,併回去才讀得到值。"""
    got = _names("金門縣縣長.pdf")
    assert [t for t, _ in got] == [1, 2, 3, 4, 5, 6]
    assert dict(got)[5] == "陳福海"
