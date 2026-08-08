"""A' 路：文字已轉成向量曲線、抽不到字的公報，用 macOS Vision(Live Text 底層) 逐格看圖讀。

與 geometry.py 分工：geometry 讀 PDF 內嵌文字，本模組讀圖；兩者輸出同一組
dataclass(Group/Person/Cell)，pipeline 可互換。

切格不做影像處理：這類 PDF 每個表格單元本身就是一個 stroke rect，直接拿座標。
直排欄位(姓名、出生年月日)字距大，Vision 會整格讀空 → 切單字後橫向重排再讀。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw

from . import geometry as geo
from . import verify

RENDER_SCALE = 4.0        # 實測 4.0 起橫排長欄位零錯字
CELL_MIN = 25             # pt，濾掉框線裝飾用的小 rect
CROP_INSET = 3            # px，往內縮避免吃到框線
DARK = 200                # 灰階二值閾值
MIN_INK_RATIO = 0.01      # 一列要有 1% 以上暗像素才算有字(濾雜點與框線殘影)
BORDER_INK = 0.85         # 一列/一欄墨水佔比達此值視為框線
GLYPH_MIN_RUN = 6         # px，字塊最小高度
GLYPH_PAD = 4             # px，字塊上下留白(切太緊會削掉筆畫)
REFLOW_GAP = 6            # px，重排後的字距

_HEADER_KEYWORDS = ("姓名", "學歷", "經歷")


def available() -> bool:
    """本機是否可用 Vision OCR(僅 macOS + pyobjc)。"""
    try:
        import Quartz  # noqa: F401
        import Vision  # noqa: F401
    except Exception:
        return False
    return True


# ---------------------------------------------------------------- Vision 呼叫

def _cg_image(img: Image.Image):
    import Quartz
    from Foundation import NSData

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), buf.tell())
    src = Quartz.CGImageSourceCreateWithData(data, None)
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def ocr_blocks(img: Image.Image, langs=("zh-Hant", "en-US"), correction=True):
    """回傳 [(text, confidence, x, y_from_bottom, height)]，未排序。"""
    import Vision

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)                    # 0 = accurate
    req.setRecognitionLanguages_(list(langs))
    req.setUsesLanguageCorrection_(correction)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        _cg_image(img), None)
    handler.performRequests_error_([req], None)
    out = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)[0]
        bb = obs.boundingBox()
        out.append((cand.string(), float(cand.confidence()),
                    float(bb.origin.x), float(bb.origin.y), float(bb.size.height)))
    return out


def ocr_lines(img: Image.Image, langs=("zh-Hant", "en-US"),
              correction=True) -> list[str]:
    """整格讀成逐行文字。同一行(如字距大的『學 歷』)會被拆成多塊且 y 有微差，
    須先分行、行內再按 x 排，否則會讀成『歷學』。

    行結構要保留給學歷/經歷切條目用(見 verify.to_bullets)。
    """
    blocks = ocr_blocks(img, langs, correction)
    if not blocks:
        return []
    blocks.sort(key=lambda b: -b[3])
    grouped: list[list] = [[blocks[0]]]
    for b in blocks[1:]:
        prev = grouped[-1][-1]
        if abs(prev[3] - b[3]) < 0.5 * max(prev[4], b[4]):
            grouped[-1].append(b)
        else:
            grouped.append([b])
    lines = ["".join(b[0] for b in sorted(line, key=lambda b: b[2])).strip()
             for line in grouped]
    return [ln for ln in lines if ln]


def ocr_text(img: Image.Image, langs=("zh-Hant", "en-US"), correction=True) -> str:
    """整格讀成單一字串(行之間直接相接,公報的換行是排版斷行)。"""
    return "".join(ocr_lines(img, langs, correction))


# ------------------------------------------------------------ 直排 → 橫排重排

def _ink_profile(img: Image.Image, axis: str) -> list[float]:
    """每一列(axis='y')或每一欄(axis='x')的墨水佔比。

    先二值化再用 PIL 縮成 1px 取平均，避免逐像素迴圈；直接取灰階平均的話，
    細筆畫的列會因為平均值接近全白而被誤判為空白。
    """
    binary = img.convert("L").point(lambda v: 0 if v < DARK else 255)
    size = (1, img.height) if axis == "y" else (img.width, 1)
    return [1.0 - v / 255 for v in
            binary.resize(size, Image.BOX).get_flattened_data()]


def trim_border(img: Image.Image) -> Image.Image:
    """裁掉 crop 邊緣殘留的框線。表格外框最粗達 5.7pt，固定內縮吃不掉，殘留的
    整列黑邊會讓投影切字看成滿格一塊(號次那種單字大格就整格讀空)。

    判準是『整行/整列幾乎全墨』；漢字行有字間空隙不會滿版，故不會削到字。
    """
    def bounds(vals: list[float]) -> tuple[int, int]:
        lo, hi = 0, len(vals)
        limit = int(len(vals) * 0.3)
        while lo < limit and vals[lo] >= BORDER_INK:
            lo += 1
        while hi > len(vals) - limit and vals[hi - 1] >= BORDER_INK:
            hi -= 1
        return lo, hi

    top, bottom = bounds(_ink_profile(img, "y"))
    left, right = bounds(_ink_profile(img, "x"))
    if (left, top, right, bottom) == (0, 0, img.width, img.height):
        return img
    return img.crop((left, top, right, bottom))


def _repair_runs(runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """修碎塊：中文直排字高相近，故以中位字高為尺。

    『黨』的下半(灬)、『7』的橫筆常被投影切成獨立塊 → 往間隙較小的一側併回去；
    併不回去的極小塊是框線殘影(會被讀成『一』『-』) → 丟掉。
    """
    if len(runs) < 2:
        return runs
    runs = list(runs)
    heights = sorted(b - t for t, b in runs)
    med = heights[len(heights) // 2]
    while True:
        small = [i for i, (t, b) in enumerate(runs) if b - t < 0.6 * med]
        best = None
        for i in small:
            for j in (i - 1, i + 1):
                if not 0 <= j < len(runs):
                    continue
                lo, hi = min(i, j), max(i, j)
                gap = runs[hi][0] - runs[lo][1]
                if gap <= 0.35 * med and (best is None or gap < best[0]):
                    best = (gap, lo, hi)
        if best is None:
            break
        _, lo, hi = best
        runs[lo:hi + 1] = [(runs[lo][0], runs[hi][1])]
    return [(t, b) for t, b in runs if b - t >= 0.4 * med]


def erase_rules(img: Image.Image) -> Image.Image:
    """抹掉格子裡殘留的框線(整行或整列都是墨的那幾條)。

    `trim_border` 只削得掉貼著邊緣的;像 105 彰化補選那種在格內、貫穿整格高度的
    直線就削不掉,而它會讓水平投影的每一列都有墨,整格的字因此切不開。
    """
    cols, rows = _ink_profile(img, "x"), _ink_profile(img, "y")
    hits = ([x for x, v in enumerate(cols) if v >= BORDER_INK]
            + [y for y, v in enumerate(rows) if v >= BORDER_INK])
    if not hits:
        return img
    out = img.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    for x, v in enumerate(cols):
        if v >= BORDER_INK:
            draw.line([(x, 0), (x, out.height)], fill="white")
    for y, v in enumerate(rows):
        if v >= BORDER_INK:
            draw.line([(0, y), (out.width, y)], fill="white")
    return out


def split_glyphs(img: Image.Image) -> list[tuple[int, int]]:
    """直排格的水平投影切字，回傳各字塊 (top, bottom)。"""
    rows = _ink_profile(erase_rules(img), "y")
    runs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(rows):
        on = v >= MIN_INK_RATIO
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= GLYPH_MIN_RUN:
                runs.append((start, i))
            start = None
    if start is not None and len(rows) - start >= GLYPH_MIN_RUN:
        runs.append((start, len(rows)))
    return _repair_runs(runs)


def reflow_vertical(img: Image.Image) -> Image.Image | None:
    """把直排格切成單字後橫向併排成一行(字距收緊)，讓 Vision 認得出是一段文字。

    單字也處理：號次那種『小數字擺在大格中央』的版面，Vision 會因文字佔比太小而
    整格讀空，裁到字身再讀就正常。
    """
    img = erase_rules(img)          # 切片會連框線一起帶走,先抹掉再切
    runs = split_glyphs(img)
    if not runs:
        return None
    glyphs = []
    for top, bottom in runs:
        g = img.crop((0, max(0, top - GLYPH_PAD),
                      img.width, min(img.height, bottom + GLYPH_PAD)))
        bbox = ImageChops.invert(g.convert("L")).getbbox()   # 裁掉左右白邊
        if bbox:
            g = g.crop((bbox[0], 0, bbox[2], g.height))
        glyphs.append(g)
    height = max(g.height for g in glyphs)
    width = sum(g.width for g in glyphs) + REFLOW_GAP * (len(glyphs) + 1)
    out = Image.new("RGB", (width, height + 2 * REFLOW_GAP), "white")
    x = REFLOW_GAP
    for g in glyphs:
        out.paste(g, (x, REFLOW_GAP + (height - g.height) // 2))
        x += g.width + REFLOW_GAP
    return out


_STRAY = re.compile(r"[A-Za-z\[\]{}()【】｜|<>~^*_=+\\/]")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def noise_score(text: str) -> int:
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


def read_cell(img: Image.Image) -> list[str]:
    """單格逐行文字。原圖優先(橫排欄位最準)，直排格再讀一次重排版擇優，
    兩邊都讀空才退到 ja-JP(救孤立數字)。

    只在「讀空才重排」是不夠的:直排欄名(105 彰化補選的表頭)Vision 讀得出東西,
    但讀出來是亂碼而不是空白,擇優才選得掉。
    """
    lines = ocr_lines(img)
    reflowed = reflow_vertical(img)
    if reflowed is not None:
        alt = ocr_lines(reflowed)
        if alt and _cleaner(alt, lines):
            return alt
    if lines:
        return lines
    return ocr_lines(img, langs=("ja-JP", "zh-Hant"))


def _cleaner(alt: list[str], base: list[str]) -> bool:
    """重排後的讀法是否明顯比原圖乾淨。

    平手一律留原圖:橫排多行的欄位(住址、學歷)重排後會被拆成好幾行,
    字沒讀錯但行結構壞掉,只有「雜訊確實比較少」才值得換。
    """
    if not "".join(base):
        return True
    return noise_score("".join(alt)) < noise_score("".join(base))


# ------------------------------------------------------------------- 格線切分

def _cluster(values, tol=3.0) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _snap(value: float, marks: list[float], tol=3.0) -> int | None:
    for i, m in enumerate(marks):
        if abs(value - m) <= tol:
            return i
    return None


def cell_rects(page) -> list[tuple[float, float, float, float]]:
    """該頁所有表格單元(stroke rect)的 (x0, top, x1, bottom)。"""
    return [(r["x0"], r["top"], r["x1"], r["bottom"]) for r in page.rects
            if r.get("stroke") and r["x1"] - r["x0"] >= CELL_MIN
            and r["bottom"] - r["top"] >= CELL_MIN]


class _Sheet:
    """一頁的格子 + 逐格 OCR 結果(取用時才讀，讀過快取)。"""

    def __init__(self, pdf_path: str, page, page_idx: int, scale: float):
        self.scale = scale
        self.rects = cell_rects(page)
        self.xs = _cluster([r[0] for r in self.rects])
        self.tops = _cluster([r[1] for r in self.rects])
        pdoc = pdfium.PdfDocument(pdf_path)
        try:
            self._img = pdoc[page_idx].render(scale=scale).to_pil()
        finally:
            pdoc.close()
        self._cache: dict[tuple[float, float], list[str]] = {}

    def crop(self, rect) -> Image.Image:
        x0, top, x1, bottom = rect
        s, pad = self.scale, CROP_INSET
        return trim_border(
            self._img.crop((max(0, int(x0 * s) + pad), max(0, int(top * s) + pad),
                            int(x1 * s) - pad, int(bottom * s) - pad)))

    def lines(self, rect) -> list[str]:
        key = (round(rect[0], 1), round(rect[1], 1))
        if key not in self._cache:
            self._cache[key] = read_cell(self.crop(rect))
        return self._cache[key]

    def text(self, rect, keep_lines=False) -> str:
        lines = self.lines(rect)
        return "\n".join(lines) if keep_lines else "".join(lines)

    def row_rects(self, top: float) -> list:
        """起始於某一列的所有格(依 x 排序)。合併格掛在它起始的那列。"""
        return sorted((r for r in self.rects if abs(r[1] - top) <= 3.0),
                      key=lambda r: r[0])

    def col_index(self, rect) -> int | None:
        return _snap(rect[0], self.xs)


def _find_header(sheet: _Sheet) -> tuple[float | None, dict[str, int], dict[str, int]]:
    """找表頭列 → (該列 top, 欄位→col index, 特殊欄(相片/基本資料)→col index)。"""
    for top in sheet.tops:
        row = sheet.row_rects(top)
        if len(row) < 6:
            continue
        texts = {}
        for rect in row:
            ci = sheet.col_index(rect)
            if ci is not None:
                texts[ci] = geo._norm(sheet.text(rect))
        joined = "".join(texts.values())
        if not all(kw in joined for kw in _HEADER_KEYWORDS):
            continue
        colmap: dict[str, int] = {}
        for fname, kws in geo.FIELD_HEADERS.items():
            for ci in sorted(texts):
                if any(kw in texts[ci] for kw in kws):
                    colmap.setdefault(fname, ci)
                    break
        special = {name: ci for name in ("相片", "基本資料")
                   for ci in sorted(texts) if name in texts[ci]}
        return top, colmap, special
    return None, {}, {}


def parse(pdf_path: str | Path, scale: float = RENDER_SCALE) -> list[geo.Group]:
    """整份公報 → Group 清單(與 geometry.parse 同型別)。"""
    groups: list[geo.Group] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            sheet = _Sheet(str(pdf_path), page, page_idx, scale)
            if not sheet.rects:
                continue
            header_top, colmap, special = _find_header(sheet)
            if header_top is None:
                continue

            photo_x = None
            if "相片" in special:
                for rect in sheet.row_rects(header_top):
                    if sheet.col_index(rect) == special["相片"]:
                        photo_x = (rect[0], rect[2])

            cur: geo.Group | None = None
            page_persons: list[geo.Person] = []
            for top in [t for t in sheet.tops if t > header_top]:
                row = sheet.row_rects(top)
                if len(row) < 3:
                    continue
                by_col = {sheet.col_index(r): r for r in row
                          if sheet.col_index(r) is not None}
                role = next((geo._norm(sheet.text(r)) for r in row
                             if geo._norm(sheet.text(r)) in geo.ROLES), None)
                if role is None:
                    continue

                if role == "總統候選人":
                    # 號次是桃紅粗體藝術字，Vision 讀不出來(『3』各種前處理都失敗)；
                    # 公報號次即組別出現順序，讀不到就用序號補。
                    ticket = next((int(t) for r in row
                                   if (t := geo._norm(sheet.text(r))).isdigit()), None)
                    cur = geo.Group(ticket=ticket or len(groups) + 1, page=page_idx)
                    groups.append(cur)
                if cur is None:
                    continue

                person = geo.Person(role="總統" if role == "總統候選人" else "副總統",
                                    page=page_idx)
                person.row_bbox = (row[0][0], top, row[-1][2], row[0][3])
                for fname, ci in colmap.items():
                    rect = by_col.get(ci)
                    if rect:
                        # 條列欄位保留換行,切條目要用(其餘欄位的換行只是排版斷行)
                        text = sheet.text(rect, keep_lines=fname in verify.BULLET_FIELDS)
                        person.cells[fname] = geo.Cell(text=text, bbox=rect)
                if "基本資料" in special and (rect := by_col.get(special["基本資料"])):
                    person.basic_cell = geo.Cell(text=sheet.text(rect), bbox=rect)

                cur.members.append(person)
                page_persons.append(person)

            if photo_x:
                geo._assign_photos(page_persons, page.images, photo_x)
    return groups
