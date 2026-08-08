"""單人一筆的公報表格解析(縣市長)。

跟總統公報的差別有兩點,都由這裡吸收:

1. **一份 PDF 常同時刊多場選舉**(市長 + 議員各選舉區)。用段落標題(「市長候選人」、
   「第12選舉區(平地原住民)候選人」)把不屬於本場的候選人濾掉;比對是按「候選人所在
   的 y 位置落在哪個標題之後」,因此連同一張表格裡上半市長、下半議員也切得開。

2. **各縣市自己排版,版式由表格自身判定**,不看縣市名:

   | 版式 | 長相 | 例 |
   |---|---|---|
   | H(表頭列) | 一列全是欄名,其後每列一位候選人 | 桃園、臺中、彰化 |
   | I(內嵌欄名) | 每位候選人一張卡片,欄名與值成對相鄰,多人並排 | 新北、臺南 |
   | V(直式欄名) | 一張表格一位候選人,欄名在上、值在正下方 | 臺北 |

   欄名右邊直接是資料 → 卡片列(I);否則是表頭列(H)。整組欄名重複代表同一列
   並排多位候選人(新竹市),切成多組欄位對照。
   直書欄名被列邊界切成上下兩段時(金門的「號／次」)先併回去,再照 H 處理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import pdfplumber

from . import geometry as geo

# 段落標題:本場要留的 / 夾帶其他選舉要濾掉的。
# 一份公報常同時刊好幾種選舉,「要留哪一種」隨本場而異——縣市長公報要濾掉議員,
# 立委公報反而必須留下寫著「第1選舉區」的段落,兩邊的規則不能共用一份。
SECTION_KEEP = re.compile(r"[市縣]長")
SECTION_SKIP = re.compile(r"議員|選舉區|代表|里長|鄉鎮市長")
_LEGISLATOR_KEEP = re.compile(r"立法委員|立委")
_LEGISLATOR_SKIP = re.compile(r"議員|[市縣]長|代表|里長|總統")
_HEADING_MAX = 30          # 標題行長度上限(超過就是內文,不是標題)


def _section_rules(role: str) -> tuple[re.Pattern, re.Pattern]:
    if "立法委員" in role or "立委" in role:
        return _LEGISLATOR_KEEP, _LEGISLATOR_SKIP
    return SECTION_KEEP, SECTION_SKIP

# 欄名 → 正規化後可能的寫法(比對用完全相等,避免把值當欄名)
_LABEL_FORMS = {
    "號次": ("號次", "號碼"),
    "相片": ("相片", "照片"),
    "姓名": ("姓名",),
    "出生年月日": ("出生年月日", "出生年月"),
    "性別": ("性別",),
    "出生地": ("出生地",),
    "政黨": ("推薦之政黨", "政黨", "登記方式"),
    "學歷": ("學歷",),
    "經歷": ("經歷",),
    "政見": ("政見",),
}


# 欄名被排版拉開對齊時,字與字之間會塞填充符號(109 屏東的『號●●●次』『姓●●●名』)
_FILLER = re.compile(r"[●○•·・‧．\.\-—─_]+")


def _pure_label(text: str) -> str | None:
    """整格就是一個欄名時回欄名。

    直書欄名被排版切成兩段後字序會交錯(『出年月日生』其實是『出生年月日』),
    所以三字以上的欄名比對「字集」而不比對字序。
    """
    for cand in (text, _FILLER.sub("", text)):
        for name, forms in _LABEL_FORMS.items():
            for form in forms:
                if cand == form:
                    return name
                if (len(form) >= 3 and len(cand) == len(form)
                        and sorted(cand) == sorted(form)):
                    return name
    return None


def _split_label(text: str) -> tuple[str, str] | None:
    """欄名和值黏在同一格時 → (欄名, 值)。"""
    for cand in (text, _FILLER.sub("", text)):
        for name, forms in _LABEL_FORMS.items():
            for form in forms:
                n = len(form)
                if len(cand) < n:
                    continue
                if cand[:n] == form or (n >= 3 and sorted(cand[:n]) == sorted(form)):
                    return name, cand[n:]
    return None


# 欄名同時列出兩欄的合併寫法(如「號次·姓名」),值也黏成「1張家豪」。
# 113 立委公報把段落標題排在同一列,欄名前面會黏上標題的碎字
# (『舉區（北投區·號次姓名』),所以只要求結尾是欄名。
_COMBINED = re.compile(r"^.{0,20}?號次\W?姓名$")
_TICKET_NAME = re.compile(r"^(\d{1,2})\s*(\S{1,20})$")

# 公報常在候選人表格後面再接一張政黨對照表,它的欄名會被當成一位候選人
_NOT_A_NAME = re.compile(r"^(政黨名稱|推薦之政黨|政黨|號次|姓名|備註|名稱)$")

# 出生年月日/性別/出生地 疊在同一格的合併欄名(縣市長寫「個人資料」,立委寫「基本資料」)
_BASIC_LABEL = "個人資料"
_BASIC_FORMS = ("個人資料", "基本資料")


@dataclass
class _Grid:
    """一張表格攤平成 (列, 欄) 的文字與 bbox,兩種版式共用。

    `text` 去掉空白供比對欄名,`raw` 保留原樣供取值;`fixed` 記下被
    `_unsplit_labels` 修過的格(那些格的值只剩正規化後的文字可用)。
    """
    text: list[list[str]]
    raw: list[list[str]]
    bbox: list[list[tuple[float, float, float, float] | None]]
    row_top: list[float]
    width: float                 # 表格總寬,用來認出橫跨整表的段落橫幅
    page: int
    fixed: set[tuple[int, int]] = dc_field(default_factory=set)

    @property
    def nrows(self) -> int:
        return len(self.text)

    def value(self, ri: int, ci: int) -> str:
        return self.text[ri][ci] if (ri, ci) in self.fixed else self.raw[ri][ci]

    def labels(self, ri: int) -> list[tuple[int, str]]:
        out = []
        for ci, t in enumerate(self.text[ri]):
            name = _pure_label(t)
            if name:
                out.append((ci, name))
        return out


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", "", geo.decode(s)).replace("　", "")


# --------------------------------------------------------------- 段落標題

_HEADING = re.compile(r"候選人\s*[:：]?$")   # 標題以「候選人」收尾,才不會誤抓經歷內文


def _marker_of(text: str, rules: tuple[re.Pattern, re.Pattern]) -> bool | None:
    """這行/這格是不是段落標題;是的話回傳「屬於本場嗎」。"""
    keep, skip = rules
    t = _norm(text)
    if len(t) > _HEADING_MAX or not _HEADING.search(t):
        return None
    if skip.search(t):
        return False
    if keep.search(t):
        return True
    return None


def _banner_of(grid: _Grid, ri: int, rules: tuple[re.Pattern, re.Pattern]) -> bool | None:
    """橫跨整張表格、只有一格有字的列 = 段落橫幅,是換一場選舉的宣告。

    花蓮把「縣議員第一選區(花蓮市)」做成這種橫幅,沒有「候選人」三個字收尾。
    限定「橫跨整表」才算,否則候選人經歷裡的『台北市議員』也會被當成橫幅。
    """
    filled = [ci for ci, t in enumerate(grid.text[ri]) if t]
    if len(filled) != 1:
        return None
    box = grid.bbox[ri][filled[0]]
    text = grid.text[ri][filled[0]]
    if box is None or len(text) > _HEADING_MAX:
        return None
    if box[2] - box[0] < grid.width * 0.6:
        return None
    skip, keep = rules[1], rules[0]
    if skip.search(text):
        return False
    if keep.search(text):
        return True
    return None


def _markers(pdf, page_grids: list[list[_Grid]],
             rules: tuple[re.Pattern, re.Pattern]) -> list[tuple[int, float, bool]]:
    """全文件的段落標題,依出現順序回 (頁, y, 是否本場)。

    標題可能是內文的一行,也可能是表格裡的一格(臺中把「選舉類別」做成表格首欄),
    兩種都收。
    """
    out: list[tuple[int, float, bool]] = []
    for pi, page in enumerate(pdf.pages):
        try:
            lines = page.extract_text_lines()
        except Exception:                      # 沒有內嵌文字的頁
            lines = []
        for ln in lines:
            keep = _marker_of(ln.get("text"), rules)
            if keep is not None:
                out.append((pi, float(ln["top"]), keep))
        for grid in page_grids[pi]:
            # 一張表格就是一位候選人時(版式 V),表格裡橫跨整列的那一格是他的學經歷,
            # 不是段落橫幅——『•盧秀燕市長競選總部發言人』會被誤判成「以下是市長選舉」。
            card = bool(_records_style_v(grid))
            for ri in range(grid.nrows):
                for t in grid.text[ri]:
                    keep = _marker_of(t, rules)
                    if keep is not None:
                        out.append((pi, grid.row_top[ri], keep))
                keep = None if card else _banner_of(grid, ri, rules)
                if keep is not None:
                    out.append((pi, grid.row_top[ri], keep))
    out.sort(key=lambda m: (m[0], m[1]))
    return out


def _in_section(markers, page: int, top: float) -> bool:
    """某位候選人(頁 page、y=top)是否屬於本場。沒有任何標題時視為屬於本場。"""
    active = True
    for mp, my, keep in markers:
        if mp < page or (mp == page and my <= top):
            active = keep
        else:
            break
    return active


# --------------------------------------------------------------- 表格 → 網格

def _ocr_fill(grid: _Grid, sheet) -> None:
    """匡線切出來的格子是好的,壞掉的只有文字層(101 金門的字型沒有對照表,
    抽出來是亂碼;有些公報的欄名乾脆畫成圖)。→ 沿用同一套格子座標,
    逐格截圖交給 Apple Vision 重讀,版式判定完全不用改。
    """
    from . import apple_ocr

    # 往內縮避免吃到框線,格子本身要夠寬才縮得動(113 臺東有寬度近乎 0 的裝飾格)
    least = 2 * apple_ocr.CROP_INSET / sheet.scale + 1
    for ri in range(grid.nrows):
        for ci in range(len(grid.text[ri])):
            box = grid.bbox[ri][ci]
            if box is None or box[2] - box[0] < least or box[3] - box[1] < least:
                continue
            text = sheet.text(box, keep_lines=True)
            grid.raw[ri][ci] = text
            grid.text[ri][ci] = _norm(text)
    grid.fixed.clear()
    _unsplit_labels(grid)


def _to_grid(page, table, page_idx: int) -> _Grid:
    extracted = table.extract()
    ncols = max((len(r) for r in extracted), default=0)
    text, raw, bbox, row_top = [], [], [], []
    for ri, row in enumerate(extracted):
        trow, rrow, brow = [], [], []
        cells = table.rows[ri].cells
        for ci in range(ncols):
            cell_text = row[ci] if ci < len(row) else ""
            trow.append(_norm(cell_text))
            rrow.append(geo.decode(cell_text))
            c = cells[ci] if ci < len(cells) else None
            brow.append(tuple(c) if c else None)
        text.append(trow)
        raw.append(rrow)
        bbox.append(brow)
        row_top.append(float(table.rows[ri].bbox[1]))
    grid = _Grid(text=text, raw=raw, bbox=bbox, row_top=row_top,
                 width=float(table.bbox[2] - table.bbox[0]), page=page_idx)
    _unsplit_labels(grid)
    return grid


# ------------------------------------------------------------ 欄名被切成兩列

def _unsplit_labels(grid: _Grid) -> None:
    """直書欄名被列邊界切成上下兩段時(金門),把欄名併回上列,值留在下列。

    公報把『號次』排成一直行,表格線正好切在『號』與『次』之間,
    於是下列那格變成「次+值」。就地修掉,後面就能照一般表頭列處理。
    """
    for ri in range(grid.nrows - 1):
        fixed: dict[int, tuple[str, str]] = {}
        for ci in range(len(grid.text[ri])):
            head = grid.text[ri][ci]
            if not head or _pure_label(head):
                continue
            got = _split_label(head + grid.text[ri + 1][ci])
            if got:
                fixed[ci] = got
        if len(fixed) >= 3 and any(n == "姓名" for n, _ in fixed.values()):
            for ci, (name, rest) in fixed.items():
                grid.text[ri][ci] = name
                grid.text[ri + 1][ci] = rest
                grid.fixed.add((ri + 1, ci))


# --------------------------------------------------------------- 版式判定

def _anchor_rows(grid: _Grid) -> list[tuple[int, int]]:
    """所有「號次」欄名的位置(內嵌版式每位候選人一個;表頭版式只在表頭列)。

    欄名後面可能黏著別的字(2018 新北把第二位的『號次2經歷』擠成一格),
    因此以「開頭是號次」認定,不要求整格剛好等於欄名——認不出來就會少一位候選人。
    """
    hits = []
    for ri in range(grid.nrows):
        for ci, t in enumerate(grid.text[ri]):
            got = _split_label(t)
            if (got and got[0] == "號次") or _COMBINED.match(t):
                hits.append((ri, ci))
    return hits


def _is_card_row(grid: _Grid, ri: int) -> bool:
    """欄名右邊直接就是資料 → 這列是候選人卡片(版式 I),不是表頭列。

    表頭列裡欄名旁邊只會是別的欄名或空格;偶爾一格合併雜訊會誤判,所以要兩處以上。
    """
    row = grid.text[ri]
    n = 0
    for ci, name in grid.labels(ri):
        nxt = row[ci + 1] if ci + 1 < len(row) else ""
        if nxt and not _pure_label(nxt):
            n += 1
    return n >= 2


def _header_rows(grid: _Grid) -> list[int]:
    """表頭列:含姓名(或號次·姓名)與其他欄名,且不是候選人卡片列。"""
    out = []
    for ri in range(grid.nrows):
        names = [n for _, n in grid.labels(ri)]
        has_name = "姓名" in names or any(_COMBINED.match(t) for t in grid.text[ri])
        has_more = any(n in ("學歷", "經歷", "政見", "出生年月日") for n in names)
        if has_name and has_more and not _is_card_row(grid, ri):
            out.append(ri)
    return out


# --------------------------------------------------------------- 版式 H

def _header_blocks(grid: _Grid, ri: int) -> list[dict[str, int]]:
    """表頭列 → 一或多組欄位對照。

    整組欄名重複出現代表同一列並排 N 位候選人(新竹市把兩位排在同一列),
    欄名重覆時就切出下一組。
    """
    blocks: list[dict[str, int]] = []
    cur: dict[str, int] = {}
    for ci, name in grid.labels(ri):
        if name in cur:
            blocks.append(cur)
            cur = {}
        cur[name] = ci
    for ci, t in enumerate(grid.text[ri]):
        if _COMBINED.match(t):
            (blocks[0] if blocks and not cur else cur).setdefault("號次·姓名", ci)
    if cur:
        blocks.append(cur)
    return blocks


_Record = tuple[dict[str, tuple[int, int]], tuple[int, int, int, int]]

# 直書姓名被列邊界切斷時,下一列只剩姓名的尾字(『李驥』/『羣』)
_NAME_TAIL = "姓名續"


def _is_name_tail(grid: _Grid, ri: int, colmap: dict[str, int], name_ci: int) -> bool:
    """只有姓名欄有字、其餘欄全空 → 這列是上一位候選人姓名的接續,不是新的候選人。"""
    if not grid.text[ri][name_ci]:
        return False
    return not any(grid.text[ri][ci] for f, ci in colmap.items()
                   if f not in ("姓名", "號次·姓名", "相片"))


def _records_style_h(grid: _Grid) -> list[_Record]:
    """表頭列之後、有姓名的每一列各是一位候選人。"""
    headers = _header_rows(grid)
    ncols = len(grid.text[0]) if grid.nrows else 0
    out: list[_Record] = []
    for hi, header_ri in enumerate(headers):
        stop = headers[hi + 1] if hi + 1 < len(headers) else grid.nrows
        blocks = _header_blocks(grid, header_ri)
        starts = [min(b.values()) for b in blocks]
        for bi, colmap in enumerate(blocks):
            name_ci = colmap.get("姓名", colmap.get("號次·姓名"))
            if name_ci is None:
                continue
            c0 = starts[bi]
            c1 = starts[bi + 1] if bi + 1 < len(starts) else ncols
            block_start = len(out)
            for ri in range(header_ri + 1, min(stop, grid.nrows)):
                if not grid.text[ri][name_ci]:
                    continue
                if len(out) > block_start and _is_name_tail(grid, ri, colmap, name_ci):
                    out[-1][0][_NAME_TAIL] = (ri, name_ci)
                    continue
                cellmap = {f: (ri, ci) for f, ci in colmap.items() if f != "號次·姓名"}
                if "號次·姓名" in colmap:
                    cellmap["姓名"] = (ri, colmap["號次·姓名"])
                out.append((cellmap, (ri, ri + 1, c0, c1)))
    return out


# --------------------------------------------------------------- 版式 I

def _cards_style_i(grid: _Grid, anchors: list[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """每個「號次」錨點展開成一張卡片 (r0, r1, c0, c1),邊界由相鄰錨點決定。"""
    anchor_rows = sorted({r for r, _ in anchors})
    cards = []
    for ri, ci in anchors:
        same_row = sorted(c for r, c in anchors if r == ri)
        nxt_c = next((c for c in same_row if c > ci), len(grid.text[ri]))
        nxt_r = next((r for r in anchor_rows if r > ri), grid.nrows)
        cards.append((ri, nxt_r, ci, nxt_c))
    return cards


# --------------------------------------------------------------- 版式 V

def _label_below(text: str) -> str | None:
    """版式 V 的欄名格:整格是欄名,或前一欄的內容溢出後接著欄名。"""
    if text in _BASIC_FORMS:
        return _BASIC_LABEL
    if _COMBINED.match(text):        # 號次·姓名 由錨點自己處理
        return None
    for name, forms in _LABEL_FORMS.items():
        for form in forms:
            if text.endswith(form):
                return name
    return None


def _records_style_v(grid: _Grid) -> list[_Record]:
    """版式 V:一張表格就是一位候選人,欄名在上、值在正下方(臺北市、113 立委)。"""
    anchor = next(((ri, ci) for ri in range(grid.nrows)
                   for ci, t in enumerate(grid.text[ri]) if _COMBINED.match(t)), None)
    if anchor is None:
        return []
    ri, ci = anchor
    if ri + 1 >= grid.nrows or not _TICKET_NAME.match(grid.text[ri + 1][ci]):
        return []
    cellmap: dict[str, tuple[int, int]] = {"號次·姓名": (ri + 1, ci)}
    # 先收「下面那格有字」的欄名;有字的才確定是值,不會被同名的空格搶走。
    # 剩下的欄名(113 立委的政見常抽不到文字)再補進來,格子本身的位置仍要留給看圖。
    for require_text in (True, False):
        for rr in range(grid.nrows - 1):
            for cc in range(len(grid.text[rr])):
                name = _label_below(grid.text[rr][cc])
                if name is None or name in cellmap:
                    continue
                if require_text and not grid.text[rr + 1][cc]:
                    continue
                if grid.bbox[rr + 1][cc] is not None:
                    cellmap[name] = (rr + 1, cc)
    return [(cellmap, (0, grid.nrows, 0, len(grid.text[0])))]


def _records_style_i(grid: _Grid) -> list[_Record]:
    out: list[_Record] = []
    for card in _cards_style_i(grid, _anchor_rows(grid)):
        cellmap = _read_card(grid, card)
        if "姓名" in cellmap:
            out.append((cellmap, card))
    return out


def _read_card(grid: _Grid, card: tuple[int, int, int, int]) -> dict[str, tuple[int, int]]:
    """卡片內每個欄名對應的值格位置。號次的值在下方,其餘在右方。"""
    r0, r1, c0, c1 = card
    found: dict[str, tuple[int, int]] = {}
    for ri in range(r0, r1):
        for ci in range(c0, c1):
            name = _pure_label(grid.text[ri][ci])
            if name is None or name in found:
                continue
            if name == "號次":
                if ri + 1 < grid.nrows:
                    found[name] = (ri + 1, ci)
            elif ci + 1 < c1:
                found[name] = (ri, ci + 1)
    return found


# --------------------------------------------------------------- 組裝

def _mk_person(grid: _Grid, role: str, cellmap: dict[str, tuple[int, int]],
               row_bbox) -> geo.Person:
    person = geo.Person(role=role, page=grid.page)
    person.row_bbox = row_bbox
    for field, (ri, ci) in cellmap.items():
        if field in ("號次", "相片", _NAME_TAIL):
            continue
        cell = geo.Cell(text=grid.value(ri, ci), bbox=grid.bbox[ri][ci])
        if field == _BASIC_LABEL:
            person.basic_cell = cell
        elif field == "號次·姓名":
            m = _TICKET_NAME.match(grid.text[ri][ci])
            person.cells["姓名"] = geo.Cell(text=m.group(2) if m else cell.text,
                                           bbox=cell.bbox)
        else:
            person.cells[field] = cell
    tail = cellmap.get(_NAME_TAIL)
    if tail is not None and "姓名" in person.cells:
        head = person.cells["姓名"]
        head_box, tail_box = head.bbox, grid.bbox[tail[0]][tail[1]]
        person.cells["姓名"] = geo.Cell(
            text=head.text + grid.value(*tail),
            bbox=_union(head_box, tail_box))
    return person


def _union(a, b):
    if a is None or b is None:
        return a or b
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _ticket(grid: _Grid, cellmap: dict[str, tuple[int, int]], fallback: int) -> int:
    pos = cellmap.get("號次") or cellmap.get("號次·姓名")
    if pos is not None:
        m = re.search(r"\d+", grid.text[pos[0]][pos[1]])
        if m:
            return int(m.group())
    return fallback


def _region_bbox(grid: _Grid, r0: int, r1: int, c0: int, c1: int):
    boxes = [grid.bbox[r][c] for r in range(r0, min(r1, grid.nrows))
             for c in range(c0, min(c1, len(grid.bbox[r]))) if grid.bbox[r][c]]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _looks_like_header(person: geo.Person) -> bool:
    """一列裡有兩個以上的「值」本身就是欄名 → 這列是表頭,不是候選人。

    逐格 OCR 時表頭列常整列都讀得出字(出生地、推薦之政黨、經歷…),
    只擋姓名那一格擋不掉,會混進一位假候選人(109 宜蘭的第 9 號)。
    """
    labels = sum(1 for f, cell in person.cells.items()
                 if f != "姓名" and _pure_label(_norm(cell.text)))
    return labels >= 2


def _assign_photo(person: geo.Person, images: list[dict], region) -> None:
    """相片欄沒有內嵌文字可比對,以「圖心落在候選人區塊內、面積最大」認定。"""
    if region is None:
        return
    x0, top, x1, bottom = region
    inside = [im for im in images
              if x0 <= (im["x0"] + im["x1"]) / 2 <= x1
              and top <= (im["top"] + im["bottom"]) / 2 <= bottom]
    if not inside:
        return
    im = max(inside, key=lambda i: (i["x1"] - i["x0"]) * (i["bottom"] - i["top"]))
    person.photo_bbox = (im["x0"], im["top"], im["x1"], im["bottom"])


def parse(pdf_path: str | Path, *, role: str, ocr: bool = False) -> list[geo.Group]:
    """回傳每位候選人各自成一組(單人)的 Group 清單。

    `ocr=True` 時不讀 PDF 的文字層,改用同一組匡線格子逐格截圖 OCR
    (文字層是亂碼或欄名被畫成圖時的退路)。
    """
    groups: list[geo.Group] = []
    seen: set[tuple[int, str]] = set()
    with geo.open_pdf(pdf_path) as pdf:
        found = []
        for pi, page in enumerate(pdf.pages):
            grids = [(t, _to_grid(page, t, pi)) for t in page.find_tables()]
            if ocr and grids:
                from . import apple_ocr

                sheet = apple_ocr._Sheet(str(pdf_path), page, pi,
                                         apple_ocr.RENDER_SCALE)
                for _t, g in grids:
                    _ocr_fill(g, sheet)
            found.append(grids)
        markers = _markers(pdf, [[g for _, g in pg] for pg in found],
                           _section_rules(role))
        highest = 0
        for page_idx, page in enumerate(pdf.pages):
            for _table, grid in found[page_idx]:
                records = (_records_style_v(grid) or _records_style_h(grid)
                           or _records_style_i(grid))

                for cellmap, span in records:
                    r0, r1, c0, c1 = span
                    if not _in_section(markers, page_idx, grid.row_top[r0]):
                        continue
                    ticket = _ticket(grid, cellmap, len(groups) + 1)
                    # 號次退回小的數字 = 換一場選舉重新編號。有些公報的「議員候選人」
                    # 標題是直排美術字,抽不出文字,只能靠這個結構訊號收尾。
                    if groups and ticket <= highest:
                        return _sorted(groups)
                    region = _region_bbox(grid, r0, r1, c0, c1)
                    person = _mk_person(grid, role, cellmap, region)
                    name = _norm(person.cells["姓名"].text) if "姓名" in person.cells else ""
                    if not name or _NOT_A_NAME.match(name) or (ticket, name) in seen:
                        continue
                    if _looks_like_header(person):
                        continue
                    seen.add((ticket, name))
                    highest = max(highest, ticket)
                    _assign_photo(person, page.images, region)
                    group = geo.Group(ticket=ticket, page=page_idx)
                    group.members.append(person)
                    party = person.cells.pop("政黨", None)
                    if party is not None:
                        group.party_cell = party
                    groups.append(group)
    return _sorted(groups)


def _sorted(groups: list[geo.Group]) -> list[geo.Group]:
    return sorted(groups, key=lambda g: (g.ticket or 0))
