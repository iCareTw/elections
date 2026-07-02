from src.voter_guide.pipeline import crop_filename


def test_crop_filename_president():
    # 民國113 → 西元2024;第16任;第1組;柯文哲;學歷
    got = crop_filename(type="president", session=16, minguo_year=113,
                        ticket=1, name="柯文哲", field="學歷")
    assert got == "president/16th_2024_ticket_1_柯文哲_學歷.png"
