from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.webapp.bulletin import bulletin_url, bulletin_url_from_record


def test_councilor_incoming_record_links_to_district_pdf() -> None:
    payload = {
        "type": "縣市議員",
        "year": 2005,
        "region": "臺中市 第06選舉區",
    }

    assert bulletin_url(payload, "councilor/2005/縣市議員_區域_臺中市.xlsx") == (
        "https://bulletin.cec.gov.tw/01選舉公報/06縣市議員/094年/"
        "13臺中市/臺中市第6選舉區議員.pdf"
    )


def test_councilor_candidate_history_links_to_district_pdf() -> None:
    record = {
        "type": "縣市議員",
        "year": 2009,
        "region": "桃園縣 第05選舉區",
    }

    assert bulletin_url_from_record(record) == (
        "https://bulletin.cec.gov.tw/01選舉公報/06縣市議員/098年/"
        "09桃園縣/桃園縣第5選舉區議員.pdf"
    )


def test_direct_municipality_councilor_candidate_history_links_to_district_pdf() -> None:
    record = {
        "type": "縣市議員",
        "year": 2014,
        "region": "臺南市 第03選舉區",
    }

    assert bulletin_url_from_record(record) == (
        "https://bulletin.cec.gov.tw/01選舉公報/05直轄市議員/103年/"
        "05臺南市/臺南市第3選舉區議員.pdf"
    )


def test_party_list_legislator_links_to_pdf_when_stable() -> None:
    record = {
        "type": "立法委員",
        "year": 2004,
        "session": 6,
        "region": "不分區",
    }

    assert bulletin_url_from_record(record) == (
        "https://bulletin.cec.gov.tw/01選舉公報/02立法委員/093年第6屆/"
        "02全國不分區及僑居國外國民/93年全國不分區及僑居國外國民立委選舉.pdf"
    )


def test_party_list_legislator_infers_session_from_year() -> None:
    record = {
        "type": "立法委員",
        "year": 2004,
        "region": "不分區",
    }

    assert bulletin_url_from_record(record) == (
        "https://bulletin.cec.gov.tw/01選舉公報/02立法委員/093年第6屆/"
        "02全國不分區及僑居國外國民/93年全國不分區及僑居國外國民立委選舉.pdf"
    )


def test_pdf_links_do_not_use_directory_query_urls() -> None:
    url = bulletin_url_from_record({
        "type": "縣市議員",
        "year": 2009,
        "region": "桃園縣 第05選舉區",
    })

    assert url is not None
    assert url.startswith("https://bulletin.cec.gov.tw/01選舉公報/")
    assert "?dir=" not in url
    assert url.endswith(".pdf")


def test_councilor_record_without_known_district_falls_back_to_region_folder() -> None:
    record = {
        "type": "縣市議員",
        "year": 2005,
        "region": "臺中市 平地原住民",
    }

    assert bulletin_url_from_record(record) == (
        "https://bulletin.cec.gov.tw/?dir=01選舉公報/06縣市議員/094年/13臺中市"
    )


def test_review_template_renders_incoming_and_possible_candidate_pdf_links() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    env.globals["bulletin_url_from_record"] = bulletin_url_from_record
    template = env.get_template("review.html")

    incoming_url = bulletin_url(
        {"type": "縣市議員", "year": 2005, "region": "臺中市 第06選舉區"},
        "councilor/2005/縣市議員_區域_臺中市.xlsx",
    )
    possible_url = bulletin_url_from_record({
        "type": "縣市議員",
        "year": 2009,
        "region": "桃園縣 第05選舉區",
    })

    html = template.render(
        election_tree={"children": {}},
        selected_id="councilor/2005/縣市議員_區域_臺中市.xlsx",
        election={"type": "councilor", "year": 2005, "label": "縣市議員_區域_臺中市"},
        record_fields=[],
        bulletin_url=incoming_url,
        matches=[{
            "id": "id_陳瑞昌_1957",
            "name": "陳瑞昌",
            "birthday": 1957,
            "elections": [{
                "type": "縣市議員",
                "year": 2009,
                "region": "桃園縣 第05選舉區",
                "party": "中國國民黨",
            }],
        }],
        incoming_birthday=1976,
        current_decision=None,
        current_record={"source_record_id": "src:1", "name": "陳瑞昌"},
        i=0,
        display_count=1,
        total_count=1,
        resolved_count=0,
        progress_pct=0,
        error="",
        decision_log=[],
        pending_count=1,
    )

    assert "選舉公報目錄" not in html
    assert "選舉公報 PDF" in html
    assert incoming_url in html
    assert possible_url in html


def test_review_template_marks_close_birthday_diff_only() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    env.globals["bulletin_url_from_record"] = bulletin_url_from_record
    template = env.get_template("review.html")

    html = template.render(
        election_tree={"children": {}},
        selected_id="councilor/2005/縣市議員_區域_臺中市.xlsx",
        election={"type": "councilor", "year": 2005, "label": "縣市議員_區域_臺中市"},
        incoming_type="縣市議員",
        record_fields=[],
        bulletin_url=None,
        matches=[
            {
                "id": "id_陳瑞昌_1975",
                "name": "陳瑞昌",
                "birthday": 1975,
                "elections": [],
                "cmp": {"birthday": "close"},
                "score": 20,
                "match_count": 1,
                "total_cmp": 1,
            },
            {
                "id": "id_陳瑞昌_1974",
                "name": "陳瑞昌",
                "birthday": 1974,
                "elections": [],
                "cmp": {"birthday": "diff"},
                "score": 0,
                "match_count": 0,
                "total_cmp": 1,
            },
        ],
        incoming_birthday=1976,
        current_decision=None,
        current_record={"source_record_id": "src:1", "name": "陳瑞昌"},
        i=0,
        display_count=1,
        total_count=1,
        resolved_count=0,
        progress_pct=0,
        error="",
        decision_log=[],
        pending_count=1,
    )

    assert 'cmp-row cmp-close' in html
    assert '差1歲' in html
    assert 'cmp-row cmp-diff' in html
    assert '差2歲' in html


def test_review_template_tags_local_type_and_region_fields() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    env.globals["bulletin_url_from_record"] = bulletin_url_from_record
    template = env.get_template("review.html")

    html = template.render(
        election_tree={"children": {}},
        selected_id="indigenous_chief/2014/新北市.xlsx",
        election={"type": "indigenous_chief", "year": 2014, "label": "新北市"},
        incoming_type="原住民區長",
        record_fields=[("選舉", "原住民區長"), ("地區", "新北市 烏來區")],
        bulletin_url=None,
        matches=[
            {
                "id": "id_測試候選人_1970",
                "name": "測試候選人",
                "birthday": 1970,
                "elections": [
                    {"type": "原住民區長", "year": 2014, "region": "新北市 烏來區", "party": "無黨籍"}
                ],
            }
        ],
        incoming_birthday=1970,
        current_decision=None,
        current_record={"source_record_id": "src:1", "name": "測試候選人"},
        i=0,
        display_count=1,
        total_count=1,
        resolved_count=0,
        progress_pct=0,
        error="",
        decision_log=[],
        pending_count=1,
    )

    assert '<span class="tag-type">原住民區長</span>' in html
    assert '<span class="tag-region">新北市 烏來區</span>' in html


def test_review_template_renders_elected_status_for_incoming_and_possible_matches() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    env.globals["bulletin_url_from_record"] = bulletin_url_from_record
    template = env.get_template("review.html")

    html = template.render(
        election_tree={"children": {}},
        selected_id="councilor/2005/縣市議員_區域_臺中市.xlsx",
        election={"type": "councilor", "year": 2005, "label": "縣市議員_區域_臺中市"},
        incoming_type="縣市議員",
        record_fields=[("選舉", "縣市議員"), ("地區", "臺中市 第06選舉區"), ("當選", 1)],
        bulletin_url=None,
        matches=[
            {
                "id": "id_測試候選人_1970",
                "name": "測試候選人",
                "birthday": 1970,
                "elections": [
                    {"type": "縣市議員", "year": 2009, "region": "桃園縣 第05選舉區", "party": "無黨籍", "elected": 0},
                    {"type": "縣市議員", "year": 2014, "region": "桃園市 第05選舉區", "party": "無黨籍", "elected": 1},
                ],
            }
        ],
        incoming_birthday=1970,
        current_decision=None,
        current_record={"source_record_id": "src:1", "name": "測試候選人"},
        i=0,
        display_count=1,
        total_count=1,
        resolved_count=0,
        progress_pct=0,
        error="",
        decision_log=[],
        pending_count=1,
    )

    assert '<span class="tag-elected is-elected">當選</span>' in html
    assert '<span class="tag-elected not-elected">未當選</span>' in html


def test_review_template_renders_party_list_legislator_pdf_without_session() -> None:
    templates_dir = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    env.globals["bulletin_url_from_record"] = bulletin_url_from_record
    template = env.get_template("review.html")

    possible_url = bulletin_url_from_record({
        "type": "立法委員",
        "year": 2004,
        "region": "不分區",
        "party": "中國國民黨",
    })

    html = template.render(
        election_tree={"children": {}},
        selected_id="councilor/2005/縣市議員_區域_臺中市.xlsx",
        election={"type": "councilor", "year": 2005, "label": "縣市議員_區域_臺中市"},
        record_fields=[],
        bulletin_url=None,
        matches=[{
            "id": "id_陳瑞昌_1975",
            "name": "陳瑞昌",
            "birthday": 1975,
            "elections": [{
                "type": "立法委員",
                "year": 2004,
                "region": "不分區",
                "party": "中國國民黨",
            }],
        }],
        incoming_birthday=1976,
        current_decision=None,
        current_record={"source_record_id": "src:1", "name": "陳瑞昌"},
        i=0,
        display_count=1,
        total_count=1,
        resolved_count=0,
        progress_pct=0,
        error="",
        decision_log=[],
        pending_count=1,
    )

    assert possible_url in html
    assert "093年第6屆" in html
    assert "93年全國不分區及僑居國外國民立委選舉.pdf" in html
    assert "https://bulletin.cec.gov.tw/?dir=01選舉公報/02立法委員/093年" not in html
