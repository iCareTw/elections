"""評分(程式算，非模型自評)：比對 A 路(幾何) 與 B 路(盲讀) 的一致度並分級。

裁判獨立性由 vision.py 保證(盲讀、只給圖)；此處只做客觀字元比對與取值規則。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# 信心五級
EXACT = "完全一致"        # 100%
NEAR = "幾乎一致"         # >90%
MOSTLY = "大部分一致"     # >80%
UNRELIABLE = "資料不可靠"  # <80%
FAILED = "無法解析"
SOFT = "看圖存疑"         # 幾何為準欄位，看圖不同但已採幾何值(不算紅字)

# 這些短欄位幾何最準、看圖最不準 → 以幾何為準，看圖僅供參考、不輕易標紅
GEO_AUTH = {"姓名", "性別", "出生地", "登記方式"}

DATE_RE = re.compile(r"(\d+)年(\d+)月(\d+)日")
_PUNCT = "、，,。.;；:：()（）「」-－　 \n\t"

_CN_DIGIT = {"〇": 0, "零": 0, "○": 0, "一": 1, "二": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_RUN = re.compile(r"[〇零○一二三四五六七八九十百]+")


def _convert_cn_run(run: str) -> str:
    if "十" in run or "百" in run:  # 正規中文數字: 三十一 / 十六 / 四十八
        total, section = 0, 0
        for ch in run:
            if ch == "百":
                section = (section or 1) * 100
                total += section
                section = 0
            elif ch == "十":
                section = (section or 1) * 10
                total += section
                section = 0
            else:
                section = _CN_DIGIT.get(ch, 0)
        total += section
        return str(total)
    return "".join(str(_CN_DIGIT.get(ch, "")) for ch in run)  # 逐字: 三一→31


def cn_to_arabic(s: str) -> str:
    return _CN_RUN.sub(lambda m: _convert_cn_run(m.group()), s)


def _norm(s: str | None) -> str:
    s = cn_to_arabic(s or "")
    return "".join(ch for ch in s if ch not in _PUNCT)


def clean_field(field: str, text: str | None) -> str | None:
    """把單格原始文字整理成乾淨值。"""
    if not text:
        return None
    if field == "出生年月日":
        return parse_minguo(text)
    if field in ("姓名", "性別", "出生地"):
        return re.sub(r"\s+", "", text).strip() or None
    # 住址 / 學歷 / 經歷 / 政見：去除換行與空白，保留頓號
    return re.sub(r"\s+", "", text).strip() or None


def parse_minguo(text: str | None) -> str | None:
    if not text:
        return None
    t = cn_to_arabic(re.sub(r"\s+", "", text))
    m = DATE_RE.search(t)
    if m:
        return f"民國{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日"
    return t or None


def _valid_date(v: str | None) -> bool:
    return bool(v and DATE_RE.search(v))


def _digits(v: str | None) -> str:
    return "".join(c for c in cn_to_arabic(v or "") if c.isdigit())


def similarity(a: str | None, b: str | None) -> float:
    na, nb = _norm(a), _norm(b)
    if not na and not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def grade_sim(sim: float) -> str:
    if sim >= 0.999:
        return EXACT
    if sim >= 0.9:
        return NEAR
    if sim >= 0.8:
        return MOSTLY
    return UNRELIABLE


def verify_field(field: str, geo_text: str | None, vision_text: str | None) -> dict:
    """回傳 {value, grade, sim, geo, vision}。"""
    geo_val = clean_field(field, geo_text)
    vis_val = clean_field(field, vision_text)

    if not geo_val and not vis_val:
        return {"value": None, "grade": FAILED, "sim": 0.0,
                "geo": None, "vision": None}

    # 取值規則
    if field == "出生年月日":
        # 取格式正確者(修正 113 排版拆散的數字)
        if _valid_date(geo_val):
            value = geo_val
        elif _valid_date(vis_val):
            value = vis_val
        else:
            value = geo_val or vis_val
    else:
        value = geo_val or vis_val  # 長欄位實證幾何較準，缺則用看圖

    # 日期特例：兩路數字相同(僅幾何丟了年月日分隔符) → 視為一致
    if (field == "出生年月日" and geo_val and vis_val
            and _digits(geo_val) == _digits(vis_val) and _digits(geo_val)):
        return {"value": value, "grade": EXACT, "sim": 1.0}

    sim = similarity(geo_val, vis_val)
    if field in GEO_AUTH:
        # 幾何為準：看圖只當參考。一致→完全一致；不同→看圖存疑(不標紅)；缺幾何→看圖頂替
        if not geo_val:
            grade = UNRELIABLE
        elif not vis_val:
            grade = SOFT
        else:
            grade = EXACT if sim >= 0.999 else SOFT
    elif geo_val and not vis_val:
        grade = FAILED  # 看圖那路沒讀到 → 無交叉證據
    elif vis_val and not geo_val:
        grade = FAILED
    else:
        grade = grade_sim(sim)

    out = {"value": value, "grade": grade, "sim": round(sim, 3)}
    if grade != EXACT:
        out["geo"] = geo_val
        out["vision"] = vis_val
    return out
