"""版面偵測:不假設欄位順序、方向或版式,從公報自身推導出表格怎麼排。

做法是拿公報上一定存在的欄位名(姓名、出生年月日、學歷…)當錨點:
- 這些標籤共線的方向,就是表頭軸;垂直於它的方向就是候選人並排的方向。
- 標籤軸落在頁面右側 → 由右往左讀(085/089/093);落在左側/上方 → 由左往右。

實測六種版面(085/089/093/097/105/113)都能正確推導,不需要為年份寫特例。
"""
from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass, field

import pypdfium2 as pdfium
from PIL import Image

FIELD_LABELS = ["號次", "候選人別", "相片", "姓名", "出生年月日", "性別",
                "出生地", "登記方式", "住址", "學歷", "經歷", "政見"]
RENDER_SCALE = 2.0
TILE_COLS, TILE_ROWS = 3, 3
TILE_OVERLAP = 0.12
TILE_ZOOM = 2.0
AXIS_TOLERANCE = 0.02       # 標籤共線判定:頁面尺寸的比例


@dataclass
class Token:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class Layout:
    """一頁的版面判定結果。"""
    page_size: tuple[int, int]
    axis: str                       # 'x' = 標籤排成直行(表格橫躺) / 'y' = 排成橫列
    axis_pos: float                 # 標籤軸位置
    labels: dict[str, Token] = field(default_factory=dict)
    tokens: list[Token] = field(default_factory=list)

    @property
    def person_axis(self) -> str:
        """候選人並排的方向(與標籤軸垂直)。"""
        return "x" if self.axis == "x" else "y"

    @property
    def right_to_left(self) -> bool:
        """標籤軸靠頁面右緣 → 資料往左展開(早期公報的直書右到左版式)。"""
        return self.axis == "x" and self.axis_pos > self.page_size[0] * 0.6

    @property
    def label_span(self) -> tuple[float, float]:
        """標籤在『非軸』方向的涵蓋範圍,即表格在該方向的大致範圍。"""
        if self.axis == "x":
            vals = [t.cy for t in self.labels.values()]
        else:
            vals = [t.cx for t in self.labels.values()]
        return (min(vals), max(vals)) if vals else (0.0, 0.0)

    def data_region(self) -> tuple[int, int, int, int]:
        """候選人資料所在的粗略範圍(x0, top, x1, bottom)。

        標籤軸的另一側就是資料側;沿標籤涵蓋範圍上下(或左右)各留一成餘裕。
        """
        W, H = self.page_size
        lo, hi = self.label_span
        pad_along = max(40.0, (hi - lo) * 0.15)
        if self.axis == "x":
            top, bottom = max(0.0, lo - pad_along), min(float(H), hi + pad_along)
            if self.right_to_left:
                return 0, int(top), int(self.axis_pos), int(bottom)
            return int(self.axis_pos), int(top), W, int(bottom)
        left, right = max(0.0, lo - pad_along), min(float(W), hi + pad_along)
        return int(left), int(self.axis_pos), int(right), H


# ------------------------------------------------------------------ OCR tokens

def _ocr(img: Image.Image) -> list[Token]:
    import Quartz
    import Vision
    from Foundation import NSData

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), buf.tell())
    src = Quartz.CGImageSourceCreateWithData(data, None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)
    req.setRecognitionLanguages_(["zh-Hant", "en-US"])
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    handler.performRequests_error_([req], None)
    W, H = img.size
    out = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)[0]
        bb = obs.boundingBox()
        out.append(Token(text=cand.string(),
                         x0=bb.origin.x * W, x1=(bb.origin.x + bb.size.width) * W,
                         top=(1 - bb.origin.y - bb.size.height) * H,
                         bottom=(1 - bb.origin.y) * H))
    return out


def tiled_ocr(img: Image.Image, cols: int = TILE_COLS, rows: int = TILE_ROWS,
              overlap: float = TILE_OVERLAP, zoom: float = TILE_ZOOM) -> list[Token]:
    """分塊放大後 OCR,再把座標映射回原圖。

    整頁一次讀在老公報上品質不足(085 只讀到 68 塊,分塊後 264 塊);小字需要放大。
    """
    W, H = img.size
    tw, th = W / cols, H / rows
    ox, oy = tw * overlap, th * overlap
    tokens: list[Token] = []
    for r in range(rows):
        for c in range(cols):
            box = (max(0, int(c * tw - ox)), max(0, int(r * th - oy)),
                   min(W, int((c + 1) * tw + ox)), min(H, int((r + 1) * th + oy)))
            tile = img.crop(box)
            tile = tile.resize((int(tile.width * zoom), int(tile.height * zoom)))
            for t in _ocr(tile):
                tokens.append(Token(text=t.text,
                                    x0=box[0] + t.x0 / zoom, x1=box[0] + t.x1 / zoom,
                                    top=box[1] + t.top / zoom,
                                    bottom=box[1] + t.bottom / zoom))
    return tokens


# --------------------------------------------------------------- 標籤軸推導

def _match_label(text: str) -> str | None:
    s = text.replace(" ", "")
    for lab in FIELD_LABELS:
        if lab in s or lab[::-1] in s:
            return lab
    return None


def _merge_split_labels(tokens: list[Token], tol: float) -> list[Token]:
    """把標籤欄裡被字距拆開的 token 併回去。

    標籤欄字距寬(『姓 名』『學 歷』),OCR 會拆成兩塊,兩塊都不含完整欄位名而漏抓。
    只併同一直行/橫列上、彼此相鄰的短 token,不影響資料欄。
    """
    short = [t for t in tokens if len(t.text.replace(" ", "")) <= 2]
    merged: list[Token] = []
    for axis in ("x", "y"):
        buckets: dict[float, list[Token]] = defaultdict(list)
        for t in short:
            v = t.cx if axis == "x" else t.cy
            for key in list(buckets):
                if abs(key - v) <= tol:
                    buckets[key].append(t)
                    break
            else:
                buckets[v].append(t)
        for group in buckets.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda t: t.top if axis == "x" else t.x0)
            span = max(t.bottom - t.top for t in group) if axis == "x" else \
                max(t.x1 - t.x0 for t in group)
            for i in range(len(group) - 1):
                a, b = group[i], group[i + 1]
                gap = (b.top - a.bottom) if axis == "x" else (b.x0 - a.x1)
                if gap > span * 2.5:
                    continue
                for text in (a.text + b.text, b.text + a.text):
                    if _match_label(text):
                        merged.append(Token(text=text,
                                            x0=min(a.x0, b.x0), x1=max(a.x1, b.x1),
                                            top=min(a.top, b.top),
                                            bottom=max(a.bottom, b.bottom)))
                        break
    return merged


def _label_hits(tokens: list[Token], tol: float) -> list[tuple[str, Token]]:
    """找出含欄位名的 token。也比對反轉字串,因為直書右到左會被讀成『名姓』。"""
    hits = []
    for t in list(tokens) + _merge_split_labels(tokens, tol):
        lab = _match_label(t.text)
        if lab:
            hits.append((lab, t))
    return hits


def detect_layout(img: Image.Image, tokens: list[Token] | None = None) -> Layout | None:
    """推導版面。找不到足夠標籤時回 None(交由呼叫端決定退路)。"""
    if tokens is None:
        tokens = tiled_ocr(img)
    tol = min(img.size) * AXIS_TOLERANCE
    hits = _label_hits(tokens, tol)
    if len(hits) < 3:
        return None

    best: tuple[int, str, float, list] | None = None
    for axis in ("x", "y"):
        tol = img.size[0 if axis == "x" else 1] * AXIS_TOLERANCE
        groups: dict[float, list] = defaultdict(list)
        for lab, t in hits:
            v = t.cx if axis == "x" else t.cy
            for key in list(groups):
                if abs(key - v) <= tol:
                    groups[key].append((lab, t))
                    break
            else:
                groups[v].append((lab, t))
        for key, members in groups.items():
            kinds = {lab for lab, _ in members}
            if best is None or len(kinds) > best[0]:
                best = (len(kinds), axis, key, members)

    if best is None or best[0] < 3:
        return None
    _, axis, key, members = best
    labels: dict[str, Token] = {}
    for lab, t in members:
        labels.setdefault(lab, t)
    return Layout(page_size=img.size, axis=axis, axis_pos=key,
                  labels=labels, tokens=tokens)


def render_page(pdf_path: str, page_idx: int = 0,
                scale: float = RENDER_SCALE) -> Image.Image:
    doc = pdfium.PdfDocument(pdf_path)
    try:
        return doc[page_idx].render(scale=scale).to_pil()
    finally:
        doc.close()
