"""學歷/經歷切條目規則(verify.to_bullets)。案例全部取自 105 公報實際版面。"""
from src.voter_guide.verify import to_bullets


def test_wrapped_text_splits_on_ideographic_comma():
    # 經歷:連續文字硬換行,續行以『、』開頭
    text = ("國民黨主席、第1屆、第2屆新北市長、行政院副院長、桃園縣第14屆\n"
            "、第15屆縣長、第4屆立法委員、國立臺灣大學教授、美國紐約市立大\n"
            "學助理教授")
    assert to_bullets(text) == (
        "- 國民黨主席\n- 第1屆\n- 第2屆新北市長\n- 行政院副院長\n- 桃園縣第14屆\n"
        "- 第15屆縣長\n- 第4屆立法委員\n- 國立臺灣大學教授\n- 美國紐約市立大學助理教授")


def test_wrapped_text_detected_by_even_line_widths():
    # 蔡英文經歷:沒有行以『、』開頭,靠『除末行外每行排滿』認出是硬換行
    text = ("民主進步黨黨主席、行政院副院長、民主進步黨不分區立法委員、總統\n"
            "府國策顧問、行政院大陸委員會主任委員、國家安全會議諮詢委員、行\n"
            "政院公平交易委員會委員、行政院大陸委員會諮詢委員、經濟部國際經\n"
            "濟組織首席法律顧問、政治大學，東吳大學法律系所及國貿所教授")
    items = to_bullets(text).splitlines()
    assert items[0] == "- 民主進步黨黨主席"
    assert items[3] == "- 總統府國策顧問"          # 斷在『總統/府』中間,要接回來
    assert "- 府國策顧問" not in items             # 續行不可自成一條


def test_one_item_per_line_keeps_inline_comma():
    # 徐欣瑩學歷:一行一條目,行內『、』屬同一條
    text = ("新竹縣立山崎國小畢業\n新竹縣立新豐國中畢業\n台北市立中山女中畢業\n"
            "國立成功大學測量工程學系學士\n國立交通大學土木系碩士、博士")
    assert to_bullets(text) == (
        "- 新竹縣立山崎國小畢業\n- 新竹縣立新豐國中畢業\n- 台北市立中山女中畢業\n"
        "- 國立成功大學測量工程學系學士\n- 國立交通大學土木系碩士、博士")


def test_short_field_splits_by_line():
    text = "倫敦政經學院法學博士\n國立台灣大學法律系學士"
    assert to_bullets(text) == "- 倫敦政經學院法學博士\n- 國立台灣大學法律系學士"


def test_parallel_session_numbers_are_rejoined():
    # 『第16、17屆縣議員』是一條,被『、』切開後要接回去
    text = "新竹縣議會第16\n、17屆縣議員、明新科技大學講師"
    assert to_bullets(text) == "- 新竹縣議會第16、17屆縣議員\n- 明新科技大學講師"


def test_empty_input():
    assert to_bullets(None) is None
    assert to_bullets("") is None
    assert to_bullets("  \n \n") is None
