"""公報 PDF 放在哪裡,就代表它是哪一場選舉。

`_data/voter_guide/` 的擺法即身分來源:

    president/113年第16任總統副總統.pdf → 總統 2024 第16任(正副成組)
    mayor/111/臺北市市長.pdf            → 縣市長 2022 臺北市(單人一號)

各類型的差別(一組幾個人、號次怎麼稱呼、切圖檔名前綴)集中在這裡,
解析與匯入都讀這份判定,不各自寫死年份或類型。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 現行與改制前的行政區(舊公報檔名會出現臺北縣、臺中縣…)
REGIONS = (
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市",
    "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣",
    "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣",
    "臺北縣", "桃園縣", "臺中縣", "臺南縣", "高雄縣",
)

PRESIDENT_ROLES = ("總統", "副總統")

# 檔名不是公報本體(罷免、公告之類),匯入清單不列入
NOT_A_GAZETTE = re.compile(r"罷免|公告")


class UnknownGazette(ValueError):
    """檔案位置看不出是哪一場選舉。"""


@dataclass(frozen=True)
class ElectionMeta:
    type: str                  # president / mayor
    minguo_year: int
    year: int                  # 西元
    session: int | None
    region: str | None
    roles: tuple[str, ...]     # 一組裡有哪些角色
    election_id: str
    label: str
    crop_slug: str             # 切圖檔名前綴
    ticket_label: str          # 號次的稱呼:「組」(正副成組) / 「號」(單人)

    @property
    def paired(self) -> bool:
        """一組多人(總統/副總統)還是單人一號。"""
        return len(self.roles) > 1


def normalize_region(text: str) -> str:
    return text.replace("台", "臺")


def _region_of(stem: str) -> tuple[str, str] | None:
    """檔名 → (地區, 職稱)。檔名前的流水號、後綴(重行選舉/補選/公報)都要能吃。"""
    s = normalize_region(re.sub(r"^\d+[_\s-]*", "", stem))
    m = re.match(r"(.+?[市縣])\s*([市縣]長)", s)
    if m and m.group(1) in REGIONS:
        return m.group(1), m.group(2)
    # 檔名寫法太自由(如「基隆選舉公報--市長」)時,退一步在字串裡找行政區名
    for region in REGIONS:
        if region in s or region[:-1] in s:
            return region, "市長" if region.endswith("市") else "縣長"
    return None


def _president_meta(path: Path) -> ElectionMeta:
    m = re.search(r"(\d+)年第(\d+)任", path.stem)
    if not m:
        raise UnknownGazette(f"總統公報檔名需含「NNN年第N任」:{path.name}")
    minguo, session = int(m.group(1)), int(m.group(2))
    year = minguo + 1911
    return ElectionMeta(
        type="president", minguo_year=minguo, year=year, session=session,
        region=None, roles=PRESIDENT_ROLES,
        election_id=f"president_{year}_{session}",
        label=f"第{session}任 {year} 總統",
        crop_slug=f"president/{session}th_{year}",
        ticket_label="組",
    )


# 公報首頁抬頭「臺灣省雲林縣第18屆縣長選舉」——檔名看不出縣市時改讀它
_TITLE_ORDINAL = r"第[\d０-９一二三四五六七八九十百零]+屆"


def _region_from_content(path: Path, max_pages: int = 3) -> tuple[str, str] | None:
    """檔名認不出縣市時,讀公報自己的抬頭。

    只認「○○縣第N屆縣長選舉」這種抬頭寫法,不是隨便在內文找到縣市名就算——
    候選人的出生地欄也會出現縣市名,那不能拿來當本場的地區。
    """
    import pdfplumber

    try:
        with pdfplumber.open(str(path)) as pdf:
            pages = pdf.pages[:max_pages]
            text = "".join(re.sub(r"\s+", "", p.extract_text() or "") for p in pages)
    except Exception:
        return None
    text = normalize_region(text)
    hits = []
    for region in REGIONS:
        m = re.search(re.escape(region) + _TITLE_ORDINAL + r"[市縣]?長", text)
        if m:
            hits.append((m.start(), region))
    if not hits:
        return None
    # 抬頭在最前面;內文(如檢舉賄選的說明)也可能出現別的縣市,取最早出現的那個
    region = min(hits)[1]
    return region, "市長" if region.endswith("市") else "縣長"


def _mayor_meta(path: Path) -> ElectionMeta:
    m = re.fullmatch(r"0*(\d+)", path.parent.name)
    if not m:
        raise UnknownGazette(f"縣市長公報需放在民國年目錄下:{path.parent.name}/{path.name}")
    minguo = int(m.group(1))
    year = minguo + 1911
    found = _region_of(path.stem) or _region_from_content(path)
    if found is None:
        raise UnknownGazette(f"檔名與公報抬頭都看不出是哪一個縣市:{path.name}")
    region, office = found
    # 同一年同一縣市可能有重行選舉/補選 → 後綴進 id,不覆蓋原場次
    extra = ""
    for kw in ("重行選舉", "重選", "補選"):
        if kw in path.stem:
            extra = "_" + kw
            break
    return ElectionMeta(
        type="mayor", minguo_year=minguo, year=year, session=None,
        region=region, roles=(office,),
        election_id=f"mayor_{year}_{region}{extra}",
        label=f"{year} {region}{office}{extra.replace('_', ' ')}",
        crop_slug=f"mayor/{year}_{region}{extra}",
        ticket_label="號",
    )


_BY_TYPE = {"president": _president_meta, "mayor": _mayor_meta}


def from_pdf_path(pdf_path: str | Path) -> ElectionMeta:
    """公報 PDF 路徑 → 選舉身分。認不出來丟 UnknownGazette。"""
    path = Path(pdf_path)
    for part in path.parts[::-1]:
        if part in _BY_TYPE:
            return _BY_TYPE[part](path)
    # 總統公報的檔名自己就寫明年份與任次,不在類型目錄下也認得
    if re.search(r"(\d+)年第(\d+)任", path.stem):
        return _president_meta(path)
    raise UnknownGazette(f"路徑不在支援的公報類型目錄下:{pdf_path}")


def is_gazette(pdf_path: str | Path) -> bool:
    """是公報本體(非罷免/選務公告)且能判定身分。"""
    path = Path(pdf_path)
    if NOT_A_GAZETTE.search(path.stem):
        return False
    try:
        from_pdf_path(path)
    except UnknownGazette:
        return False
    return True


def find_gazettes(base: str | Path) -> list[Path]:
    """公報目錄下所有能判定身分的公報 PDF。

    副檔名大小寫不拘(中選會的檔案混用 .pdf/.PDF),未支援的類型目錄自動略過。
    """
    return sorted(p for p in Path(base).rglob("*")
                  if p.is_file() and p.suffix.lower() == ".pdf" and is_gazette(p))
