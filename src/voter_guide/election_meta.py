"""公報 PDF 放在哪裡,就代表它是哪一場選舉。

`_data/voter_guide/` 的擺法即身分來源:

    president/113年第16任總統副總統.pdf → 總統 2024 第16任(正副成組)
    mayor/111/臺北市市長.pdf            → 縣市長 2022 臺北市(單人一號)
    legislator/11th_113/02區域立法委員/02臺北市/第1選舉區/….pdf
                                        → 立委 2024 第11屆 臺北市第1選舉區

各類型的差別(一組幾個人、號次怎麼稱呼、切圖檔名前綴、左樹擺在哪一層)集中在這裡,
解析與匯入都讀這份判定,不各自寫死年份或類型。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
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
LEGISLATOR_ROLE = "立法委員"

# 檔名不是公報本體(罷免、公告、投開票所地點之類),匯入清單不列入
NOT_A_GAZETTE = re.compile(r"罷免|公告|投開票所|投票所")

# 一組裡怎麼擺人:正副成組 / 單人一號 / 一個政黨一份名單
PAIRED = "paired"
SINGLE = "single"
PARTY_LIST = "party_list"


class UnknownGazette(ValueError):
    """檔案位置看不出是哪一場選舉。"""


@dataclass(frozen=True)
class ElectionMeta:
    type: str                  # president / mayor / legislator
    minguo_year: int
    year: int                  # 西元
    session: int | None
    region: str | None
    roles: tuple[str, ...]     # 一組裡有哪些角色(不分區名單人數不固定,為空)
    election_id: str
    label: str
    crop_slug: str             # 切圖檔名前綴
    ticket_label: str          # 號次的稱呼:「組」(正副成組) / 「號」(單人)
    nav_path: tuple[str, ...] = ()   # 校對台左樹的位置,最後一段是這場自己的標題
    layout: str = SINGLE       # 版面型態,見 PAIRED / SINGLE / PARTY_LIST
    category: str = ""         # 立委才有:區域 / 不分區 / 原住民 / 補選
    districts: tuple[int, ...] = ()   # 檔名寫的選舉區(合刊公報會有好幾個)

    @property
    def paired(self) -> bool:
        """一組多人(總統/副總統)還是單人一號。"""
        return self.layout == PAIRED

    @property
    def by_district(self) -> bool:
        """本場的分區是用號碼的(區域、補選),還是用名稱的(平地/山地原住民)。"""
        return self.category in (DISTRICT, BY_ELECTION)

    @property
    def splits_by_scope(self) -> bool:
        """一份公報可能合刊本類型的好幾場(各自從第1號重編),需要拆場。"""
        return self.category in (DISTRICT, BY_ELECTION, NATIVE)

    def for_scope(self, scope: int | str) -> ElectionMeta:
        """同一份公報裡某一區自己的場次。合刊的公報靠這個拆成多場。

        scope 是選舉區號(區域、補選)或分區名稱(平地原住民、山地原住民)。
        """
        seat = f"第{scope}選舉區" if isinstance(scope, int) else scope
        full = f"{self.region}{seat}" if isinstance(scope, int) else seat
        return replace(
            self,
            election_id=f"legislator_{self.year}_{self.category}_{full}",
            label=f"第{self.session}屆 {self.year} {full}立委"
                  + ("補選" if self.category == BY_ELECTION else ""),
            crop_slug=f"legislator/{self.year}_{self.category}_{full}",
            nav_path=self.nav_path[:-1] + (seat,),
        )


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
        nav_path=("總統", f"第{session}任 {year}"),
        layout=PAIRED,
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
        nav_path=("縣市長", str(year), f"{region}{extra.replace('_', ' ')}"),
        layout=SINGLE,
    )


# --------------------------------------------------------------------- 立法委員
#
# 中選會四屆的目錄擺法不一致,一律用「屆次目錄 + 分類目錄 + 縣市目錄 + 檔名」判定:
#
#     08th_101/district/01臺北市/臺北市立委選舉第1選區.pdf
#     11th_113/02區域立法委員/02臺北市/第1選舉區/臺北市立委第1選舉區.pdf
#
# 分類目錄叫 district 或「02區域立法委員」都認;檔名寫著補選的,即使放在區域
# 目錄下(109 臺中市第2選舉區缺額補選)也歸補選。

_SESSION_DIR = re.compile(r"^(\d+)th[_-](\d+)$")

DISTRICT = "區域"
PARTY = "不分區"
NATIVE = "原住民"
BY_ELECTION = "補選"

_CATEGORY_DIRS = (
    ("district", DISTRICT), ("party", PARTY),
    ("native", NATIVE), ("by-election", BY_ELECTION),
)
_CATEGORY_WORDS = ((BY_ELECTION, "補選"), (PARTY, "不分區"),
                   (NATIVE, "原住民"), (DISTRICT, "區域"))

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_DIGITS = "0-9０-９一二三四五六七八九十"
# 「第1選舉區」「第1、2選舉區」「1.8.9選區」都要吃;「第10屆…」不能誤判成選舉區
_DISTRICT_RE = re.compile(
    rf"第?\s*([{_DIGITS}]+(?:\s*[.、,，及]\s*[{_DIGITS}]+)*)\s*選舉?區")


def _strip_seq(name: str) -> str:
    """目錄名前面的排序流水號(02臺北市 → 臺北市)。"""
    return re.sub(r"^\d+[_\s-]*", "", name)


def _to_int(token: str) -> int | None:
    token = token.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if token.isdigit():
        return int(token)
    if token in _CN_NUM:
        return _CN_NUM[token]
    if len(token) == 2 and token[0] == "十" and token[1] in _CN_NUM:   # 十一、十二
        return 10 + _CN_NUM[token[1]]
    return None


def district_numbers(text: str) -> list[int]:
    """文字裡提到的選舉區號。一份公報可能同時刊好幾區(新北市 1.8.9 選區)。"""
    out: list[int] = []
    for m in _DISTRICT_RE.finditer(text):
        for token in re.split(r"[.、,，及]", m.group(1)):
            n = _to_int(token)
            if n is not None and n not in out:
                out.append(n)
    return sorted(out)


def _district_label(nums: list[int]) -> str | None:
    return f"第{'、'.join(str(n) for n in nums)}選舉區" if nums else None


def _category_of(dirs: list[str], stem: str) -> str | None:
    """分類目錄 + 檔名 → 區域 / 不分區 / 原住民 / 補選。"""
    if "補選" in stem or "缺額" in stem:
        return BY_ELECTION
    head = dirs[0] if dirs else ""
    for key, category in _CATEGORY_DIRS:
        if head == key:
            return category
    for category, word in _CATEGORY_WORDS:
        if word in head:
            return category
    return None


def native_kind(text: str) -> str:
    """平地/山地;101 把兩者合刊成一份。"""
    plain, hill = "平地" in text, "山地" in text
    if plain and hill:
        return "平地山地原住民"
    if hill:
        return "山地原住民"
    if plain:
        return "平地原住民"
    return "原住民"


# 2008 以前的複數選區有些不編號,直接叫北區/南區(高雄市)
_NAMED_SEAT = re.compile(r"(北區|南區)")


def _find_region(texts: list[str]) -> str | None:
    for text in texts:
        norm = normalize_region(_strip_seq(text))
        for region in REGIONS:
            if region in norm:
                return region
    # 檔名省略了縣/市(「花蓮立委補選」)時退一步用前綴比對
    for text in texts:
        norm = normalize_region(_strip_seq(text))
        for region in REGIONS:
            if region[:-1] in norm:
                return region
    return None


def _part_of(stem: str, category: str) -> str | None:
    """同一場被拆成多份 PDF 時的分辨後綴,不加會互相覆蓋。"""
    for side in ("正面", "背面"):
        if side in stem:
            return side
    if category == PARTY:
        m = re.search(r"(\d+)\s*$", stem)      # 105 的不分區公報拆成 1～4 份
        if m:
            return f"之{m.group(1)}"
    return None


def _legislator_meta(path: Path) -> ElectionMeta:
    parts = list(path.parts)
    idx = len(parts) - 1 - parts[::-1].index("legislator")
    rel = parts[idx + 1:]
    if len(rel) < 2:
        raise UnknownGazette(f"立委公報需放在「NNth_民國年」目錄下:{path.name}")
    m = _SESSION_DIR.match(rel[0])
    if not m:
        raise UnknownGazette(f"立委公報的屆次目錄需寫成「08th_101」:{rel[0]}")
    session, minguo = int(m.group(1)), int(m.group(2))
    year = minguo + 1911

    dirs = [_strip_seq(d) for d in rel[1:-1]]
    stem = normalize_region(path.stem)
    category = _category_of(dirs, stem)
    if category is None:
        raise UnknownGazette(f"看不出是區域/不分區/原住民/補選:{'/'.join(rel)}")

    region = _find_region(dirs[1:]) or _find_region([stem])
    nums = district_numbers(stem) or district_numbers("/".join(dirs[1:]))
    district = _district_label(nums)
    if district is None:                   # 2008 以前有些選區不編號(高雄市北區/南區)
        named = _NAMED_SEAT.search(stem)
        district = named.group(1) if named else None
    part = _part_of(stem, category)

    if category == PARTY:
        scope, leaf = "全國不分區", "全國不分區"
    elif category == NATIVE:
        scope = leaf = native_kind("/".join(dirs) + stem)
    else:
        if region is None:
            raise UnknownGazette(f"看不出是哪一個縣市:{'/'.join(rel)}")
        scope = f"{region}{district or ''}"
        leaf = district or region
    if part:
        scope, leaf = f"{scope}_{part}", f"{leaf} {part}"

    if category == DISTRICT:
        # 左樹一律「區域 → 縣市 → 選舉區」三層。只有一個選舉區的縣市也照樣開一層,
        # 否則有的縣市點得開、有的直接是連結,看起來很亂。
        seat = district or "選舉區"          # 全縣一席時官方寫法就是「○○縣選舉區」
        nav_tail: tuple[str, ...] = (
            DISTRICT, region, f"{seat} {part}" if part else seat)
    elif category == BY_ELECTION:
        nav_tail = (BY_ELECTION, f"{region}{district or ''}{(' ' + part) if part else ''}")
    else:
        nav_tail = (scope.split("_")[0],) + ((part,) if part else ())

    suffix = "補選" if category == BY_ELECTION else ""
    return ElectionMeta(
        type="legislator", minguo_year=minguo, year=year, session=session,
        region=region, roles=() if category == PARTY else (LEGISLATOR_ROLE,),
        election_id=f"legislator_{year}_{category}_{scope}",
        label=f"第{session}屆 {year} {scope.replace('_', ' ')}立委{suffix}",
        crop_slug=f"legislator/{year}_{category}_{scope}",
        ticket_label="號",
        nav_path=("立法委員", f"第{session}屆 {year}") + nav_tail,
        layout=PARTY_LIST if category == PARTY else SINGLE,
        category=category,
        districts=tuple(nums),
    )


_BY_TYPE = {"president": _president_meta, "mayor": _mayor_meta,
            "legislator": _legislator_meta}


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
    """是公報本體(非罷免/選務公告)且能判定身分。

    罷免案的目錄名寫在上層(11th_113/06罷免案/…),所以檔名與所在目錄都要看。
    """
    path = Path(pdf_path)
    if any(NOT_A_GAZETTE.search(part) for part in (path.stem, *path.parts[:-1])):
        return False
    try:
        from_pdf_path(path)
    except UnknownGazette:
        return False
    return True


def find_gazettes(base: str | Path) -> list[Path]:
    """公報目錄下所有能判定身分的公報 PDF。

    副檔名大小寫不拘(中選會的檔案混用 .pdf/.PDF),未支援的類型目錄自動略過。
    同一份檔案被放進多個選舉區目錄時(臺南市第5、6選舉區合刊)只留一份,
    否則同一場會被匯入兩次。
    """
    seen: set[tuple] = set()
    out = []
    for p in sorted(Path(base).rglob("*")):
        if not (p.is_file() and p.suffix.lower() == ".pdf" and is_gazette(p)):
            continue
        key = (p.name, p.stat().st_size)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out
