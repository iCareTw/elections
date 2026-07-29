"""掃描圖公報 → Group 清單:版面推導 + 網格重建 + 逐格 OCR。

與 geometry(讀 PDF 內嵌文字)、apple_ocr(讀 PDF 向量格線)同輸出型別,可互換。
本模組專門處理『PDF 裡什麼都沒有,只有一張掃描照片』的公報(085/089/093/097)。

分工:格線給邊界,標籤給名字。欄位列的橫線要在『單一候選人欄內』找——跨欄的合併格
(如正副共用的登記方式)會打斷整頁投影,但不會打斷單欄內的線。標籤只負責回答那一列
是哪個欄位,因此不必每個標籤都被 OCR 認出(085 只認出 4 個仍可運作)。
"""
from __future__ import annotations

import re

from PIL import Image

from . import geometry as geo
from . import verify
from .apple_ocr import read_cell
from .layout import Layout, detect_layout, render_page
from .scan_grid import (aligned_surface, auto_threshold, build_grid,
                        continuous_rules, even_runs, extend_columns, find_rules,
                        ink_profile)

ROLE_KEYWORDS = ("總統候選人", "副總統候選人")
RENDER_SCALE = 2.0        # 格線偵測用;更高的解析度反而讓 085 的等距線判定失準
CELL_INSET = 4
UPSCALE = 3
# 放大後重讀的上限。掃描網點在原尺寸容易誤判(『步黨』→『三沙』),放大能救回;
# 但整段學經歷放大後像素過多、OCR 反而變慢又不準,故只放大到中等大小的格。
UPSCALE_BELOW = 1200
READ_FACTOR = 2.5         # 讀取用圖的倍率(相對於格線圖)。實測 2.5 起才讀得出『步黨』
_DIGITS = re.compile(r"\d+")
# 夾在中文裡的字母或括號類符號幾乎都是網點誤判(『陳K扁』『國民【』)
_STRAY = re.compile(r"[A-Za-z\[\]{}()【】｜|<>~^*_=+\\/]")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_BIRTH_RE = re.compile(r"\d+年\d+月\d+日")


def reverse_vertical(line: str) -> str:
    """直書右到左的一行 → 正常閱讀順序。

    OCR 由左往右讀,整行是倒的(『扁水陳』→『陳水扁』)。但數字本身是橫排的,
    不能跟著倒(『40年2月18日』會變成『04年2月81日』),故先抽出、反轉後再放回。
    """
    tokens = []
    last = 0
    for m in _DIGITS.finditer(line):
        tokens.extend(line[last:m.start()])
        tokens.append(m.group())
        last = m.end()
    tokens.extend(line[last:])
    return "".join(reversed(tokens))


def _named_bands(layout: Layout, rules: list[int], offset: tuple[int, int],
                 ) -> list[tuple[str, int, int]]:
    """(欄位名, 起, 迄):列邊界取自格線,欄位名由標籤座標對應過去。

    邊界不用標籤推算——標籤未必每個都被 OCR 認出(085 只認出 4 個),但格線是完整的。
    標籤只負責回答『這一列是哪個欄位』。
    """
    if len(rules) < 2:
        return []
    axis_is_x = layout.axis == "x"
    shift = offset[1] if axis_is_x else offset[0]
    bands = list(zip(rules, rules[1:]))
    out: list[tuple[str, int, int]] = []
    for name, tok in layout.labels.items():
        pos = (tok.cy if axis_is_x else tok.cx) - shift
        for lo, hi in bands:
            if lo <= pos <= hi:
                out.append((name, lo, hi))
                break
    out.sort(key=lambda b: b[1])
    return out


def _row_rules(img: Image.Image, xs: list[int], thresh: int) -> list[int]:
    """欄位列的橫線。逐一候選人欄各找一次,取最完整的一組。

    列邊界必須在『單一候選人欄內』找:跨欄的合併格(正副共用的登記方式)會打斷整頁
    投影。但個別欄可能印刷偏淡(085 最左欄只找到 5 條,最右欄有 11 條),故取最完整者。
    """
    best: list[int] = []
    for x0, x1 in zip(xs, xs[1:]):
        column = img.crop((x0, 0, x1, img.height))
        found = find_rules(ink_profile(column, "y", thresh), min_ink=0.7)
        if len(found) > len(best):
            best = found
    return best


def _infer_name_band(bands: list[tuple[str, int, int]],
                     rules: list[int]) -> list[tuple[str, int, int]]:
    """姓名列漏標時,用位置關係補:公報上姓名一定緊鄰在出生年月日的前一列。

    085 的標籤欄字太小,只認出 4 個標籤(缺姓名);但列邊界是完整的,補得回來。
    """
    named = {name for name, _, _ in bands}
    if "姓名" in named or "出生年月日" not in named:
        return bands
    birth_lo = next(lo for name, lo, _ in bands if name == "出生年月日")
    taken = {(lo, hi) for _, lo, hi in bands}
    candidates = [(lo, hi) for lo, hi in zip(rules, rules[1:])
                  if hi <= birth_lo and (lo, hi) not in taken and hi - lo >= 8]
    if not candidates:
        return bands
    return sorted(bands + [("姓名", *candidates[-1])], key=lambda b: b[1])


def _role_band(img: Image.Image, columns: list[tuple[int, int]], rules: list[int],
               bands: list[tuple[str, int, int]],
               reverse: bool) -> tuple[int, int] | None:
    """『候選人別』那一列的範圍——直接讀內容找,不靠標籤。

    085 的標籤欄字太小,OCR 認不出『候選人別』四個字,但資料欄裡的
    『副總統候選人』本身讀得很清楚,用它反推該列位置即可。取命中最多欄的那一列,
    不能找到一個就停——單一欄可能剛好讀空。
    """
    named = {(lo, hi) for _, lo, hi in bands}
    probe = columns[:4]
    best, best_hits = None, 0
    for lo, hi in zip(rules, rules[1:]):
        if (lo, hi) in named or hi - lo < 8:
            continue
        hits = sum(
            any(kw in _read(img, (cx0, lo, cx1, hi), keep_lines=False,
                            reverse=reverse).replace(" ", "")
                for kw in ROLE_KEYWORDS)
            for cx0, cx1 in probe)
        if hits > best_hits:
            best, best_hits = (lo, hi), hits
    return best


def _classify(text: str) -> str | None:
    """靠內容認出欄位。標籤欄字小,OCR 常漏認(085 只認出 4 個標籤)。"""
    flat = text.replace("\n", "").replace(" ", "")
    if not flat:
        return None
    if flat in ("男", "女"):
        return "性別"
    if any(kw in flat for kw in ("推薦", "連署", "無黨", "黨")):
        return "登記方式"
    if _BIRTH_RE.search(flat):
        return "出生年月日"
    return None


def _infer_unnamed_bands(img: Image.Image, columns: list[tuple[int, int]],
                         rules: list[int], bands: list[tuple[str, int, int]],
                         reverse: bool, hires: Image.Image | None = None
                         ) -> list[tuple[str, int, int]]:
    """沒對到標籤的列,改讀內容判斷是哪個欄位。"""
    named_rows = {(lo, hi) for _, lo, hi in bands}
    named = {name for name, _, _ in bands}
    # 多探幾欄:連署參選者的登記方式欄是空的(085 陳履安、089 宋楚瑜),
    # 只看前兩欄會誤判成該列沒有內容。
    # 除了逐欄,也試正副合併的範圍:登記方式常是兩欄共用一格,逐欄只會讀到半句
    # (089 讀成『中國』+『民黨』),認不出關鍵字。
    spans = list(columns[:4])
    spans += [(min(a[0], b[0]), max(a[1], b[1]))
              for a, b in zip(columns[::2], columns[1::2])][:2]
    out = list(bands)
    for lo, hi in zip(rules, rules[1:]):
        if (lo, hi) in named_rows or hi - lo < 8:
            continue
        for cx0, cx1 in spans:
            field = _classify(_read(img, (cx0, lo, cx1, hi),
                                    keep_lines=False, reverse=reverse,
                                    hires=hires, factor=READ_FACTOR))
            if field and field not in named:
                out.append((field, lo, hi))
                named.add(field)
                break
    return sorted(out, key=lambda b: b[1])


def _photo_band(bands: list[tuple[str, int, int]],
                rules: list[int]) -> tuple[int, int] | None:
    """相片列。標籤沒認出時取『候選人別與姓名之間最高的那一列』——相片格最高。"""
    for name, lo, hi in bands:
        if name == "相片":
            return lo, hi
    named = {name for name, _, _ in bands}
    if "姓名" not in named:
        return None
    name_lo = next(lo for n, lo, _ in bands if n == "姓名")
    taken = {(lo, hi) for _, lo, hi in bands}
    above = [(lo, hi) for lo, hi in zip(rules, rules[1:])
             if hi <= name_lo and (lo, hi) not in taken]
    return max(above, key=lambda b: b[1] - b[0]) if above else None


def _role_of(text: str) -> str:
    flat = text.replace("\n", "").replace(" ", "")
    return "副總統" if "副" in flat else "總統"


def _merged_bands(img: Image.Image, xs: list[int],
                  bands: list[tuple[str, int, int]], thresh: int) -> set[str]:
    """找出跨欄合併的欄位:該列在候選人分界線上『沒有線』就是被合併了。

    登記方式常由正副共用一格,分開讀會各拿到半句(『民主進』+『黨推薦』)。
    """
    from .scan_grid import continuity

    merged: set[str] = set()
    inner = xs[1:-1]
    if not inner:
        return merged
    for name, lo, hi in bands:
        # 號次橫跨整組;候選人別必須逐欄讀(正副在此列的值本來就不同)
        if hi - lo < 8 or name in ("號次", "候選人別"):
            continue
        scores = [continuity(img, x, lo, hi, thresh) for x in inner]
        if scores and min(scores) < 0.5:
            merged.add(name)
    return merged


def _person_columns(grid_img: Image.Image, xs: list[int],
                    right_to_left: bool) -> list[tuple[int, int]]:
    """候選人欄範圍。右到左版式要反轉,讓第一位候選人排在最前面。"""
    spans = list(zip(xs, xs[1:]))
    return list(reversed(spans)) if right_to_left else spans


def _noise_score(text: str) -> int:
    """判讀瑕疵的量。兩種都是掃描網點造成的:

    - 夾在中文之間的字母或括號類符號(『陳K扁』的 K、『國民【』的【)。不算數字——
      日期欄的數字本來就夾在『年月日』之間,算進去會把正確的日期判成雜訊。
    - 相鄰的重複中文字(『推推薦』)。合併格橫跨兩欄時容易把同一字讀到兩次。
    """
    flat = text.replace("\n", "")
    stray = sum(1 for i, ch in enumerate(flat)
                if _STRAY.match(ch)
                and any(_CJK.match(flat[j]) for j in (i - 1, i + 1)
                        if 0 <= j < len(flat)))
    repeats = sum(1 for a, b in zip(flat, flat[1:])
                  if a == b and _CJK.match(a))
    return stray + repeats


def _pick_reading(base: str, bigger: str) -> str:
    """原尺寸與高解析兩種讀法擇優。

    依序看:雜訊少者勝 → 讀到的字多者勝(缺字是主要失敗模式) → 平手時取高解析,
    因為它是真的多算出細節,不是插值猜的。
    """
    if not bigger:
        return base
    if not base:
        return bigger
    noise = _noise_score(base) - _noise_score(bigger)
    if noise != 0:
        return bigger if noise > 0 else base
    return bigger if len(bigger.replace("\n", "")) >= len(base.replace("\n", "")) else base


def _hires_surface(pdf_path: str, scale: float, region: tuple[int, int, int, int],
                   skew: float) -> Image.Image | None:
    """與格線圖對齊、解析度高 READ_FACTOR 倍的讀取用圖。失敗則回 None(退回插值放大)。"""
    try:
        page = render_page(pdf_path, 0, scale * READ_FACTOR)
        box = tuple(int(v * READ_FACTOR) for v in region)
        return aligned_surface(page.crop(box), skew, READ_FACTOR)
    except Exception:
        return None


def _crop(img: Image.Image, box: tuple[int, int, int, int],
          factor: float = 1.0) -> Image.Image:
    x0, top, x1, bottom = box
    pad = CELL_INSET * factor
    return img.crop((max(0, int(x0 * factor + pad)), max(0, int(top * factor + pad)),
                     min(img.width, int(x1 * factor - pad)),
                     min(img.height, int(bottom * factor - pad))))


def _read(img: Image.Image, box: tuple[int, int, int, int],
          *, keep_lines: bool, reverse: bool = False,
          hires: Image.Image | None = None, factor: float = 1.0) -> str:
    crop = _crop(img, box)
    if crop.width < 8 or crop.height < 8:
        return ""

    def render(image: Image.Image) -> str:
        lines = read_cell(image)
        if reverse:
            lines = [reverse_vertical(ln) for ln in lines]
        return "\n".join(lines) if keep_lines else "".join(lines)

    text = render(crop)
    # 掃描網點在原尺寸容易誤判(陳水扁→陳K7扁、步黨→三沙)。高解析度重讀是真的補回
    # 細節,放大插值則是次選;兩者都讀後擇優(缺字與雜訊都會被扣分)。
    if hires is not None:
        big = _crop(hires, box, factor)
        if big.width >= 8 and big.height >= 8:
            text = _pick_reading(text, render(big))
    elif max(crop.size) < UPSCALE_BELOW:
        text = _pick_reading(text, render(
            crop.resize((crop.width * UPSCALE, crop.height * UPSCALE), Image.LANCZOS)))
    return text


def parse(pdf_path: str, *, scale: float = RENDER_SCALE) -> list[geo.Group]:
    """掃描圖公報 → Group 清單。無法推導版面時回空清單。"""
    page = render_page(pdf_path, 0, scale)
    layout = detect_layout(page)
    if layout is None:
        return []

    region = layout.data_region()
    sub = page.crop(region)
    grid = build_grid(sub)
    img = grid.image
    y0, y1 = int(img.height * 0.1), int(img.height * 0.9)
    thresh = auto_threshold(img)
    xs = extend_columns(img, even_runs(continuous_rules(img, grid.xs, y0, y1, thresh)),
                        y0, y1, thresh)
    if len(xs) < 2:
        return []

    rules = _row_rules(img, xs, thresh)
    bands = _named_bands(layout, rules, (region[0], region[1]))
    if not bands:
        return []
    hires = _hires_surface(pdf_path, scale, region, grid.skew)
    columns = _person_columns(img, xs, layout.right_to_left)

    if not any(n == "候選人別" for n, _, _ in bands):
        role_band = _role_band(img, columns, rules, bands, layout.right_to_left)
        if role_band:
            bands = sorted(bands + [("候選人別", *role_band)], key=lambda b: b[1])
    bands = _infer_name_band(bands, rules)
    bands = _infer_unnamed_bands(img, columns, rules, bands,
                                 layout.right_to_left, hires)

    merged = _merged_bands(img, xs, bands, thresh)
    photo = _photo_band(bands, rules)
    persons: list[tuple[str, dict[str, str], Image.Image | None]] = []
    for idx, (cx0, cx1) in enumerate(columns):
        values: dict[str, str] = {}
        for name, lo, hi in bands:
            if name in ("號次", "相片"):
                continue
            box = (cx0, lo, cx1, hi)
            if name in merged:
                # 正副共用的合併格(登記方式):兩欄一起讀,否則各讀到半句
                partner = columns[idx + 1] if idx % 2 == 0 else columns[idx - 1]
                box = (min(cx0, partner[0]), lo, max(cx1, partner[1]), hi)
            values[name] = _read(img, box,
                                 keep_lines=name in verify.BULLET_FIELDS,
                                 reverse=layout.right_to_left,
                                 hires=hires, factor=READ_FACTOR)
        role_text = values.pop("候選人別", "")
        crop = None
        if photo:
            crop = img.crop((cx0 + CELL_INSET, photo[0] + CELL_INSET,
                             cx1 - CELL_INSET, photo[1] - CELL_INSET))
        persons.append((role_text, values, crop))

    groups: list[geo.Group] = []
    current: geo.Group | None = None
    for role_text, values, crop in persons:
        role = _role_of(role_text)
        is_vice = role == "副總統"
        person = geo.Person(role=role, page=0)
        person.photo_image = crop        # 掃描圖無內嵌影像,改帶已裁好的圖
        for name, text in values.items():
            if text:
                person.cells[name] = geo.Cell(text=text, bbox=None)
        if not is_vice or current is None:
            current = geo.Group(ticket=len(groups) + 1, page=0)
            groups.append(current)
            current.president = person
        else:
            current.vice = person
    return groups
