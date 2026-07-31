from pathlib import Path

import pytest

from src.voter_guide.pipeline import crop_filename, parse_pdf

ROOT = Path(__file__).resolve().parents[2]
PRESIDENT_PDF = ROOT / "_data/voter_guide/president/113年第16任總統副總統.pdf"


def test_crop_filename_president():
    # 民國113 → 西元2024;第16任;第1組;柯文哲;學歷
    got = crop_filename(slug="president/16th_2024",
                        ticket=1, name="柯文哲", field="學歷")
    assert got == "president/16th_2024_ticket_1_柯文哲_學歷.png"


def test_crop_filename_platform_omits_name():
    # 政見為組層級,檔名不綁人名
    got = crop_filename(slug="president/16th_2024",
                        ticket=2, name="任何人", field="政見")
    assert got == "president/16th_2024_ticket_2_政見.png"


def test_parse_pdf_entries_include_platform_key(tmp_path):
    if not PRESIDENT_PDF.exists():
        pytest.skip("local president PDF fixture not available")
    result, _ = parse_pdf(str(PRESIDENT_PDF), "113", tmp_path, use_vision=False)
    assert result
    for entry in result:
        assert "政見" in entry                      # 每組都有政見欄(值可能為 None)
        assert "政見" in entry["_verify"]


def test_parse_pdf_records_include_page(tmp_path):
    if not PRESIDENT_PDF.exists():
        pytest.skip("local president PDF fixture not available")
    # use_vision=False → 幾何即可,快速;頁碼來自 person.page
    result, _ = parse_pdf(str(PRESIDENT_PDF), "113", tmp_path, use_vision=False)
    assert result
    for entry in result:
        for role in ("總統", "副總統"):
            if role in entry:
                assert isinstance(entry[role]["頁碼"], int)
