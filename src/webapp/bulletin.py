from __future__ import annotations

import re

from src.session_years import SESSION_YEARS

_BULLETIN_DIR = "https://bulletin.cec.gov.tw/?dir=01選舉公報"
_BULLETIN_FILE = "https://bulletin.cec.gov.tw/01選舉公報"
_BULLETIN_ROOT = "https://bulletin.cec.gov.tw"
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

_MNA_SESSION_BY_YEAR: dict[int, int] = {
    1991: 2,
    1996: 3,
    2001: 3,
    2005: 4,
}

_LEGISLATOR_PARTY_LIST_URLS: dict[int, str] = {
    2: "/01選舉公報/02立法委員/081年第2屆/02全國不分區及僑居國外國民/81年全國不分區及僑居國外國民立委選舉.pdf",
    3: "/01選舉公報/02立法委員/084年第3屆/02全國不分區及僑居國外國民/84年全國不分區及僑居國外國民立委選舉.pdf",
    4: "/01選舉公報/02立法委員/087年第4屆/02全國不分區及僑居國外國民/87年全國不分區及僑居國外國民立委選舉.pdf",
    5: "/01選舉公報/02立法委員/090年第5屆/02全國不分區及僑居國外國民/90年全國不分區及僑居國外國民立委選舉.pdf",
    6: "/01選舉公報/02立法委員/093年第6屆/02全國不分區及僑居國外國民/93年全國不分區及僑居國外國民立委選舉.pdf",
    7: "/01選舉公報/02立法委員/097年第7屆/02全國不分區及僑居國外國民/97年全國不分區及僑居國外國民立委選舉.pdf",
    8: "/01選舉公報/02立法委員/101年第8屆/02全國不分區及僑居國外國民/101年全國不分區及僑居國外國民立委選舉.pdf",
    9: "/?dir=01選舉公報%2F02立法委員%2F105年第9屆%2F02全國不分區及僑居國外國民",
    10: "/01選舉公報/02立法委員/109年第10屆/03全國不分區立法委員/全國不分區及僑居國外國民立法委員選舉%20.pdf",
    11: "/01選舉公報/02立法委員/113年第11屆/05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf",
}

_LEGISLATOR_DISTRICT_URLS: dict[int, str] = {
    2: "/?dir=01選舉公報%2F02立法委員%2F081年第2屆%2F01區域",
    3: "/?dir=01選舉公報%2F02立法委員%2F084年第3屆%2F01區域",
    4: "/?dir=01選舉公報%2F02立法委員%2F087年第4屆%2F01區域",
    5: "/?dir=01選舉公報%2F02立法委員%2F090年第5屆%2F01區域",
    6: "/?dir=01選舉公報%2F02立法委員%2F093年第6屆%2F01區域",
    7: "/?dir=01選舉公報%2F02立法委員%2F097年第7屆%2F01區域",
    8: "/?dir=01選舉公報%2F02立法委員%2F101年第8屆%2F01區域",
    9: "/?dir=01選舉公報%2F02立法委員%2F105年第9屆%2F01區域",
    10: "/?dir=01選舉公報%2F02立法委員%2F109年第10屆%2F02區域立法委員",
    11: "/?dir=01選舉公報%2F02立法委員%2F113年第11屆%2F02區域立法委員",
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


def _councilor_url(year: int, region: str) -> str | None:
    if year == 2002:
        return None

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


def _legislator_party_url(year: int, session: int | None) -> str:
    if session and session in _LEGISLATOR_PARTY_LIST_URLS:
        return f"{_BULLETIN_ROOT}{_LEGISLATOR_PARTY_LIST_URLS[session]}"
    return _dir(f"02立法委員/{_roc(year)}")


def _legislator_district_url(year: int, session: int | None) -> str:
    if session and session in _LEGISLATOR_DISTRICT_URLS:
        return f"{_BULLETIN_ROOT}{_LEGISLATOR_DISTRICT_URLS[session]}"
    return _dir(f"02立法委員/{_roc(year)}")


def _session_from_election_id(election_id: str) -> int | None:
    match = re.search(r"(\d+)th", election_id)
    return int(match.group(1)) if match else None


def _mna_url(year: int, region: str, session: int | None) -> str | None:
    session = session or _MNA_SESSION_BY_YEAR.get(year)
    is_party_list = region in {"全國", "不分區", "全國不分區及僑居國外國民"}

    if session == 4:
        return _file("09國大代表/094年/國大第四屆.pdf")

    if session == 3:
        if is_party_list:
            return _file(
                "09國大代表/085年/02全國不分區及僑居國外國民/"
                "00全國不分區及僑居國外國民國大代表.pdf"
            )
        return _dir("09國大代表/085年/01區域")

    if session == 2:
        if is_party_list:
            return _file(
                "09國大代表/080年/02全國不分區及僑居國外國民/"
                "00全國不分區及僑居國外國民國大代表.pdf"
            )
        return _dir("09國大代表/080年/01區域")

    return None


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
    session = int(session_raw) if session_raw is not None else _session_from_election_id(election_id)

    roc = _roc(year)
    city = _city(region)

    if type_ in ("國家元首_總統", "國家元首_副總統"):
        return _dir(f"01總統副總統/{roc}")

    if type_ == "立法委員":
        session = session or _LEGISLATOR_SESSION_BY_YEAR.get(year)
        if region in {"全國", "不分區", "全國不分區及僑居國外國民"}:
            return _legislator_party_url(year, session)
        if session:
            return _legislator_district_url(year, session)
        return _dir(f"02立法委員/{roc}")

    if type_ == "國大代表":
        return _mna_url(year, region, session)

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

    if type_ == "村里長":
        roc_num = _roc_num(year)
        if roc_num >= _TOWNSHIP_EEBULLETIN_FROM_ROC:
            code = _EEBULLETIN_COUNTY.get(city)
            if code:
                return _ee(f"{roc_num:03d}/{code}{city}/05村里長")
            return _ee(f"{roc_num:03d}")
        return None

    return None


def bulletin_url_from_record(record: dict) -> str | None:
    return bulletin_url(record)


def bulletin_link_label(record: dict, url: str | None = None) -> str:
    if not url:
        return "無公報"
    if record.get("type") == "國大代表" and url.startswith(_BULLETIN_DIR):
        return "選舉公報目錄"
    return "選舉公報 PDF"
