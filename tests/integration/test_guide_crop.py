from __future__ import annotations

from pathlib import Path

import pytest

from src.voter_guide.guide_crop import crop_photo

ROOT = Path(__file__).resolve().parents[2]
PRESIDENT_PDF = ROOT / "_data/voter_guide/president/113年第16任總統副總統.pdf"


def test_crop_photo_writes_image(tmp_path):
    if not PRESIDENT_PDF.exists():
        pytest.skip("local president PDF fixture not available")
    dest = tmp_path / "sub" / "photo.png"
    # 任取頁面左上一塊區域(pt),只要能裁出有效 PNG 即可
    out = crop_photo(str(PRESIDENT_PDF), 0, (50, 50, 150, 200), dest)
    assert Path(out) == dest
    assert dest.exists()

    from PIL import Image
    with Image.open(dest) as im:
        assert im.width > 0 and im.height > 0
