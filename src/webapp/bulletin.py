from __future__ import annotations

import re

from src.session_years import SESSION_YEARS

_BULLETIN_DIR = "https://bulletin.cec.gov.tw/?dir=01選舉公報"
_BULLETIN_FILE = "https://bulletin.cec.gov.tw/01選舉公報"
_EE_BULLETIN = "https://eebulletin.cec.gov.tw"

_TOWNSHIP_EEBULLETIN_FROM_ROC = 103

# 直轄市升格年（西元）；0 表示一直是直轄市
_DIRECT_FROM: dict[str, int] = {
    "臺北市": 0, "高雄市": 0,
    "新北市": 2010, "臺中市": 2010, "臺南市": 2010,
    "桃園市": 2014,
}

# bulletin 縣市議員/縣市長 縣市目錄編號 — 舊行政區（2009年以前，含094年/098年）
_BULLETIN_COUNTY_OLD: dict[str, str] = {
    "臺北縣": "07", "基隆市": "08", "桃園縣": "09",
    "新竹市": "10", "新竹縣": "11", "苗栗縣": "12",
    "臺中市": "13", "臺中縣": "14", "彰化縣": "15",
    "南投縣": "16", "雲林縣": "17", "嘉義市": "18",
    "嘉義縣": "19", "臺南市": "20", "臺南縣": "21",
    "高雄縣": "22", "屏東縣": "23", "臺東縣": "24",
    "花蓮縣": "25", "宜蘭縣": "26", "澎湖縣": "27",
    "金門縣": "28", "連江縣": "29",
}

# bulletin 縣市議員/縣市長 縣市目錄編號 — 2010 年直轄市議員（099年）
_BULLETIN_COUNTY_2010_DIRECT: dict[str, str] = {
    "臺北市": "01", "新北市": "02", "臺中市": "03",
    "臺南市": "04", "高雄市": "05",
}

# bulletin 縣市議員/縣市長 縣市目錄編號 — 新行政區（2014年起，含103年/107年/111年）
_BULLETIN_COUNTY_NEW_DIRECT: dict[str, str] = {
    "臺北市": "01", "新北市": "02", "桃園市": "03",
    "臺中市": "04", "臺南市": "05", "高雄市": "06",
}
_BULLETIN_COUNTY_NEW_NON_DIRECT: dict[str, str] = {
    "新竹縣": "07", "苗栗縣": "08", "彰化縣": "09",
    "南投縣": "10", "雲林縣": "11", "嘉義縣": "12",
    "屏東縣": "13", "宜蘭縣": "14", "花蓮縣": "15",
    "臺東縣": "16", "澎湖縣": "17", "金門縣": "18",
    "連江縣": "19", "基隆市": "20", "新竹市": "21",
    "嘉義市": "22",
}

# eebulletin 縣市目錄編號（103/107/111 年一致）
_EEBULLETIN_COUNTY: dict[str, str] = {
    "臺北市": "02", "新北市": "03", "桃園市": "04",
    "臺中市": "05", "臺南市": "06", "高雄市": "07",
    "新竹縣": "08", "苗栗縣": "09", "彰化縣": "10",
    "南投縣": "11", "雲林縣": "12", "嘉義縣": "13",
    "屏東縣": "14", "宜蘭縣": "15", "花蓮縣": "16",
    "臺東縣": "17", "澎湖縣": "18", "金門縣": "19",
    "連江縣": "20", "基隆市": "21", "新竹市": "22",
    "嘉義市": "23",
}

_LEGISLATOR_SESSION_BY_YEAR: dict[int, int] = {
    year: session for session, year in SESSION_YEARS.items()
}


def _roc(year: int) -> str:
    return f"{year - 1911:03d}年"


def _roc_num(year: int) -> int:
    return year - 1911


def _dir(path: str) -> str:
    return f"{_BULLETIN_DIR}/{path}"


def _file(path: str) -> str:
    return f"{_BULLETIN_FILE}/{path}"


def _ee(path: str) -> str:
    return f"{_EE_BULLETIN}/?dir={path}"


def _city(region: str) -> str:
    m = re.match(r"(.+?[縣市])", region or "")
    return m.group(1) if m else ""


def _is_direct(city: str, year: int) -> bool:
    from_year = _DIRECT_FROM.get(city)
    return from_year is not None and year >= from_year


def _bulletin_county_code(city: str, year: int) -> str | None:
    if year == 2010:
        return _BULLETIN_COUNTY_2010_DIRECT.get(city)
    if year >= 2014:
        return _BULLETIN_COUNTY_NEW_DIRECT.get(city) or _BULLETIN_COUNTY_NEW_NON_DIRECT.get(city)
    return _BULLETIN_COUNTY_OLD.get(city)


def _councilor_url(year: int, region: str) -> str:
    roc = _roc(year)
    city = _city(region)
    direct = _is_direct(city, year)

    subfolder = "05直轄市議員" if direct else "06縣市議員"
    code = _bulletin_county_code(city, year)
    if not code:
        return _dir(f"{subfolder}/{roc}")

    county_folder = f"{code}{city}"
    base = f"{subfolder}/{roc}/{county_folder}"
    return _dir(base)


def bulletin_url(payload: dict, election_id: str = "") -> str | None:
    """
    從含 type/year/region/session 的 dict 產生中選會公報連結。
    支援 source_record payload 與 candidate_elections row 兩種來源。
    """
    type_ = payload.get("type") or ""
    year_raw = payload.get("year")
    if year_raw is None:
        return None
    year = int(year_raw)
    region = payload.get("region") or ""
    session_raw = payload.get("session")
    session = int(session_raw) if session_raw is not None else None

    roc = _roc(year)
    city = _city(region)

    if type_ in ("國家元首_總統", "國家元首_副總統"):
        return _dir(f"01總統副總統/{roc}")

    if type_ == "立法委員":
        session = session or _LEGISLATOR_SESSION_BY_YEAR.get(year)
        if region in {"全國", "不分區", "全國不分區及僑居國外國民"}:
            if session:
                return _dir(f"02立法委員/{roc}第{session}屆/02全國不分區及僑居國外國民")
            return _dir(f"02立法委員/{roc}")
        if session:
            return _dir(f"02立法委員/{roc}第{session}屆/01區域")
        return _dir(f"02立法委員/{roc}")

    if type_ == "縣市首長":
        if _is_direct(city, year):
            return _dir(f"03直轄市長/{roc}")
        # 2022年 縣市長多了 01紙本公報 中間層
        if year == 2022:
            return _dir(f"04縣市長/{roc}/01紙本公報")
        code = _bulletin_county_code(city, year)
        if code:
            return _dir(f"04縣市長/{roc}/{code}{city}")
        return _dir(f"04縣市長/{roc}")

    if type_ == "縣市議員":
        return _councilor_url(year, region)

    if type_ == "鄉鎮市長":
        roc_num = _roc_num(year)
        if roc_num >= _TOWNSHIP_EEBULLETIN_FROM_ROC:
            code = _EEBULLETIN_COUNTY.get(city)
            if code:
                return _ee(f"{roc_num:03d}/{code}{city}/03鄉鎮市長")
            return _ee(f"{roc_num:03d}")
        return None

    return None


def bulletin_url_from_record(record: dict) -> str | None:
    return bulletin_url(record)
