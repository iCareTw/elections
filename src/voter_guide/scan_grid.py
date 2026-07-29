"""掃描圖公報的網格重建:校正歪斜 → 自適應二值化 → 投影找格線。

為什麼需要這層:085/089/093/097 的 PDF 內部沒有文字也沒有線條,整份只是一張
掃描照片。格線只存在於像素裡,得自己找出來。三個實測過的關鍵點:

- **歪斜**:掃描歪 0.2 度,1300px 高的直線就橫移 4~5px,投影會被抹平(093 校正前
  投影峰值 0.26,校正後 0.88)。
- **墨色**:085 整份是淺藍色印刷,寫死的灰階門檻完全抓不到線,門檻必須看背景亮度定。
- **線寬**:直排文字整欄都是墨,佔比不輸給線,只能靠『線很細、文字欄很寬』區分。
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

MAX_SKEW_DEG = 2.0        # 掃描歪斜的搜尋範圍
SKEW_STEP = 0.1
DARK_RATIO = 0.88         # 門檻 = 背景亮度 * 此值
MAX_RULE_PX = 8           # 超過此寬度的墨帶是文字欄,不是線
MIN_RULE_INK = 0.35       # 一條線要佔該方向長度的比例(合併格會讓線中斷)
EVEN_TOLERANCE = 0.06     # 等距判定容許誤差


@dataclass
class Grid:
    """一塊表格區的格線。xs/ys 為該區域內的座標(左上角為原點)。"""
    image: Image.Image
    xs: list[int]
    ys: list[int]
    skew: float

    @property
    def col_spans(self) -> list[tuple[int, int]]:
        return list(zip(self.xs, self.xs[1:]))

    @property
    def row_spans(self) -> list[tuple[int, int]]:
        return list(zip(self.ys, self.ys[1:]))


def auto_threshold(img: Image.Image) -> int:
    """依背景亮度定二值化門檻(085 的淺藍印刷用固定門檻會全部漏掉)。"""
    hist = img.convert("L").histogram()
    background = max(range(256), key=lambda i: hist[i])
    return max(60, int(background * DARK_RATIO))


def ink_profile(img: Image.Image, axis: str, thresh: int) -> list[float]:
    """每列(y)/每欄(x)的墨水佔比。"""
    binary = img.convert("L").point(lambda v: 0 if v < thresh else 255)
    size = (1, img.height) if axis == "y" else (img.width, 1)
    return [1.0 - v / 255 for v in
            binary.resize(size, Image.BOX).get_flattened_data()]


def find_rules(profile: list[float], min_ink: float = MIN_RULE_INK,
               max_width: int = MAX_RULE_PX) -> list[int]:
    """從投影找出格線位置:墨水佔比夠高、且夠細的墨帶。"""
    out: list[int] = []
    start = None
    for i, v in enumerate(profile):
        if v >= min_ink and start is None:
            start = i
        elif v < min_ink and start is not None:
            if i - start <= max_width:
                out.append((start + i - 1) // 2)
            start = None
    if start is not None and len(profile) - start <= max_width:
        out.append((start + len(profile) - 1) // 2)
    return out


def _skew_score(profile: list[float]) -> float:
    """校正得分:對齊時墨水會集中到少數幾欄,故取投影的平方和(能量)。

    不能用單一峰值評分——頁面其他區塊的長邊框會獨力衝高峰值,把角度帶偏
    (089/093 曾因此選到 -0.6 度,實際只歪 0.1~0.3 度)。
    """
    return sum(v * v for v in profile)


def deskew(img: Image.Image, thresh: int,
           max_deg: float = MAX_SKEW_DEG) -> tuple[Image.Image, float]:
    """搜尋讓格線投影最集中的旋轉角(掃描歪斜會讓投影找不到線)。"""
    best_angle, best_score = 0.0, -1.0
    steps = int(max_deg / SKEW_STEP)
    for i in range(-steps, steps + 1):
        angle = i * SKEW_STEP
        score = _skew_score(ink_profile(_rotated(img, angle), "x", thresh))
        if score > best_score:
            best_score, best_angle = score, angle
    return _rotated(img, best_angle), best_angle


def _margin_for(img: Image.Image, angle: float) -> int:
    return int(abs(angle) * img.height / 57.3) + 4


def _rotated(img: Image.Image, angle: float, margin: int | None = None) -> Image.Image:
    if angle == 0 and margin is None:
        return img
    out = img.rotate(angle, resample=Image.BILINEAR, fillcolor="white")
    if margin is None:
        margin = _margin_for(img, angle)
    return out.crop((margin, margin, out.width - margin, out.height - margin))


def aligned_surface(img: Image.Image, skew: float, factor: float) -> Image.Image:
    """與 build_grid 產出的圖對齊、但解析度高 factor 倍的讀取用圖。

    掃描網點在低解析度會誤判(『步黨』→『三沙』),而單純把小圖放大是插值、補不回
    細節,必須真的用更高倍率重新算圖。裁切邊界依同一比例換算,座標才對得上。
    """
    margin = int(_margin_for(img, skew) * factor)
    return _rotated(img, skew, margin=margin)


def even_runs(marks: list[int], tolerance: float = EVEN_TOLERANCE,
              min_step: int = 40) -> list[int]:
    """取出等距的最長一段。候選人欄一定等寬,雜訊線不會。

    嚴格『連續』比對:每一步都必須落在預測位置上,中間缺一條就換一組種子。
    否則會把恰好倍數關係的雜訊線串成假等距(089 曾串出 513/487/515)。
    """
    if len(marks) < 3:
        return marks
    best: list[int] = []
    for i in range(len(marks) - 2):
        for j in range(i + 1, len(marks) - 1):
            step = marks[j] - marks[i]
            if step < min_step:
                continue
            run = [marks[i], marks[j]]
            for k in range(j + 1, len(marks)):
                gap = marks[k] - run[-1]
                if abs(gap - step) <= step * tolerance:
                    run.append(marks[k])
                elif gap > step * (1 + tolerance):
                    break            # 中斷就停,不跨過缺口硬接
            if len(run) > len(best):
                best = run
    return best if len(best) >= 3 else marks


def build_grid(img: Image.Image, *, do_deskew: bool = True) -> Grid:
    """一塊表格區 → 格線。"""
    thresh = auto_threshold(img)
    skew = 0.0
    if do_deskew:
        img, skew = deskew(img, thresh)
    xs = find_rules(ink_profile(img, "x", thresh))
    ys = find_rules(ink_profile(img, "y", thresh))
    return Grid(image=img, xs=xs, ys=ys, skew=skew)


def _has_rule_at(img: Image.Image, x: int, y0: int, y1: int, thresh: int,
                 window: int = 6, min_ink: float = MIN_RULE_INK) -> int | None:
    """在預測位置附近的小窗口內找線,回傳實際位置。

    只看局部,所以不受表格外的版面干擾——這是外推能成立的原因。
    """
    lo, hi = max(0, x - window), min(img.width, x + window + 1)
    if hi - lo < 1 or y1 - y0 < 10:
        return None
    strip = img.crop((lo, y0, hi, y1))
    profile = ink_profile(strip, "x", thresh)
    best = max(range(len(profile)), key=lambda i: profile[i])
    return lo + best if profile[best] >= min_ink else None


def extend_columns(img: Image.Image, seeds: list[int], y0: int, y1: int,
                   thresh: int | None = None, limit: int | None = None) -> list[int]:
    """以等距種子線為基準往兩側外推,補齊種子區外的欄位分界。

    種子區只要框到 3 條等距線就夠,不必事先知道表格有多寬。`limit` 限制總欄數,
    避免外推衝出表格、把隔壁區塊的線也收進來。
    """
    if len(seeds) < 2:
        return seeds
    if thresh is None:
        thresh = auto_threshold(img)
    step = round((seeds[-1] - seeds[0]) / (len(seeds) - 1))
    if step <= 0:
        return seeds

    # 基準取中位數而非最小值:個別種子線可能因印刷淡化偏低,用最小值會過嚴
    # (085 曾因此只外推到 6 欄,實際有 8 欄)
    scores = sorted(continuity(img, x, y0, y1, thresh) for x in seeds)
    reference = scores[len(scores) // 2]
    out = list(seeds)
    for direction in (-1, 1):
        cursor = out[0] if direction < 0 else out[-1]
        while limit is None or len(out) < limit:
            predicted = cursor + direction * step
            if not (0 <= predicted < img.width):
                break
            found = _has_rule_at(img, predicted, y0, y1, thresh)
            # 找到既有線代表外推繞回自己,再走下去會無限重複
            if found is None or any(abs(found - v) <= 2 for v in out):
                break
            # 新線必須跟種子一樣貫穿表格,否則是表格外的東西(089 曾多收 2 條)
            if continuity(img, found, y0, y1, thresh) < reference * 0.75:
                break
            out.append(found)
            cursor = found
    return sorted(out)


def continuity(img: Image.Image, x: int, y0: int, y1: int,
               thresh: int, half_width: int = 3) -> float:
    """一條線貫穿 y0..y1 的程度(0~1)。"""
    strip = img.crop((max(0, x - half_width), y0,
                      min(img.width, x + half_width + 1), y1))
    if strip.width < 1 or strip.height < 1:
        return 0.0
    return max(ink_profile(strip, "x", thresh))


def continuous_rules(img: Image.Image, marks: list[int], y0: int, y1: int,
                     thresh: int | None = None,
                     ratio: float = 0.75) -> list[int]:
    """只留貫穿整個表格高度的線,濾掉直排文字欄造成的假線。

    這一步必須在找等距之前:直排文字整欄都是墨,墨量不輸給格線,若先找等距會把
    文字欄串成假的等距序列(093 曾因此得到間距 417,真實欄寬是 380)。
    實測貫穿度差距明顯——093 表格線 ≥0.88,文字欄 ≤0.51。
    """
    if len(marks) < 3:
        return marks
    if thresh is None:
        thresh = auto_threshold(img)
    scored = [(x, continuity(img, x, y0, y1, thresh)) for x in marks]
    cutoff = max(s for _, s in scored) * ratio
    kept = [x for x, s in scored if s >= cutoff]
    return kept if len(kept) >= 3 else marks
