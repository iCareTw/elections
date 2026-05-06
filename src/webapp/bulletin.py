from __future__ import annotations

import re

from src.session_years import SESSION_YEARS

_BULLETIN_DIR_BASE = "https://bulletin.cec.gov.tw/?dir=01選舉公報"
_BULLETIN_FILE_BASE = "https://bulletin.cec.gov.tw/01選舉公報"
_EE_BULLETIN_BASE = "https://eebulletin.cec.gov.tw"

# 直轄市升格時間表
_ALWAYS_DIRECT = {"臺北市", "高雄市"}
_DIRECT_FROM_2010 = {"新北市", "臺中市", "臺南市"}
_DIRECT_FROM_2014 = {"桃園市"}

_LOCAL_REGION_CODES = {
    "臺北市": "01",
    "高雄市": "02",
    "臺北縣": "07",
    "新北市": "07",
    "基隆市": "08",
    "桃園縣": "09",
    "新竹市": "10",
    "新竹縣": "11",
    "苗栗縣": "12",
    "臺中市": "13",
    "臺中縣": "14",
    "彰化縣": "15",
    "南投縣": "16",
    "雲林縣": "17",
    "嘉義市": "18",
    "嘉義縣": "19",
    "臺南市": "20",
    "臺南縣": "21",
    "高雄縣": "22",
    "屏東縣": "23",
    "臺東縣": "24",
    "花蓮縣": "25",
    "宜蘭縣": "26",
    "澎湖縣": "27",
    "金門縣": "28",
    "連江縣": "29",
}

_DIRECT_REGION_CODES_2010 = {
    "臺北市": "01",
    "新北市": "02",
    "臺中市": "03",
    "臺南市": "04",
    "高雄市": "05",
}

_DIRECT_REGION_CODES_2014 = {
    "臺北市": "01",
    "新北市": "02",
    "桃園市": "03",
    "臺中市": "04",
    "臺南市": "05",
    "高雄市": "06",
}

_LEGISLATOR_SESSIONS_BY_YEAR = {year: session for session, year in SESSION_YEARS.items()}


def _roc(year: int) -> str:
    return f"{year - 1911:03d}年"


def _roc_number(year: int) -> int:
    return year - 1911


def _dir_url(*parts: str) -> str:
    return "/".join([_BULLETIN_DIR_BASE, *parts])


def _file_url(*parts: str) -> str:
    return "/".join([_BULLETIN_FILE_BASE, *parts])


def _region_name(region: str) -> str:
    head = region.split()[0] if region else ""
    match = re.match(r"(.+?[縣市])", head)
    return match.group(1) if match else head


def _district_number(region: str) -> int | None:
    match = re.search(r"第\s*0*(\d+)\s*選(?:舉)?區", region)
    return int(match.group(1)) if match else None


def _is_direct_municipality(region: str, year: int) -> bool:
    city = _region_name(region)
    if city in _ALWAYS_DIRECT:
        return True
    if city in _DIRECT_FROM_2010 and year >= 2010:
        return True
    if city in _DIRECT_FROM_2014 and year >= 2014:
        return True
    return False


def _region_folder(region: str, year: int, *, direct: bool) -> str | None:
    name = _region_name(region)
    if not name:
        return None

    if direct:
        codes = _DIRECT_REGION_CODES_2014 if year >= 2014 else _DIRECT_REGION_CODES_2010
    else:
        codes = _LOCAL_REGION_CODES

    code = codes.get(name)
    return f"{code}{name}" if code else None


def _council_bulletin_url(type_: str, year: int, region: str) -> str:
    direct = _is_direct_municipality(region, year)
    subfolder = "05直轄市議員" if direct else "06縣市議員"
    base_parts = [subfolder, _roc(year)]

    region_folder = _region_folder(region, year, direct=direct)
    if not region_folder:
        return _dir_url(*base_parts)

    base_parts.append(region_folder)

    district = _district_number(region)
    region_name = _region_name(region)
    if type_ == "縣市議員" and not direct and district is not None:
        return _file_url(*base_parts, f"{region_name}第{district}選舉區議員.pdf")

    return _dir_url(*base_parts)


def _legislator_bulletin_url(year: int, region: str, session: int | None) -> str:
    session = session or _LEGISLATOR_SESSIONS_BY_YEAR.get(year)
    folder = f"{_roc(year)}第{session}屆" if session else _roc(year)

    if region in {"全國", "不分區", "全國不分區及僑居國外國民"}:
        party_list_folder = "02全國不分區及僑居國外國民"
        base_parts = ["02立法委員", folder, party_list_folder]
        if session and session <= 8:
            return _file_url(*base_parts, f"{_roc_number(year)}年全國不分區及僑居國外國民立委選舉.pdf")
        return _dir_url(*base_parts)

    return _dir_url("02立法委員", folder, "01區域")


def bulletin_url_from_record(record: dict) -> str | None:
    """
    從 candidate_elections 的單筆紀錄（type/year/region/session）產生公報目錄連結。
    用於 Possible Existing Candidates 的選舉歷史清單。
    """
    type_ = record.get("type", "")
    year = record.get("year")
    region = record.get("region", "")
    session = record.get("session")

    if not year:
        return None

    roc = _roc(year)

    if type_ in ("國家元首_總統", "國家元首_副總統"):
        return _dir_url("01總統副總統", roc)

    if type_ == "立法委員":
        return _legislator_bulletin_url(year, region, session)

    if type_ == "縣市首長":
        subfolder = "03直轄市長" if _is_direct_municipality(region, year) else "04縣市長"
        return _dir_url(subfolder, roc)

    if type_ == "縣市議員":
        return _council_bulletin_url(type_, year, region)

    if type_ == "鄉鎮市長":
        roc_year = _roc_number(year)
        if roc_year >= 103:
            return f"{_EE_BULLETIN_BASE}/?dir={roc_year}"
        return None

    return None


def bulletin_url(payload: dict, election_id: str) -> str | None:
    """
    從 incoming record 的 payload + election_id 產生公報目錄連結。
    election_id 用於區分直轄市 vs 縣市（比 region 更可靠）。
    """
    type_ = payload.get("type", "")
    year = payload.get("year")
    region = payload.get("region", "")
    session = payload.get("session")

    if not year:
        return None

    roc = _roc(year)

    if type_ in ("國家元首_總統", "國家元首_副總統"):
        return _dir_url("01總統副總統", roc)

    if type_ == "立法委員":
        return _legislator_bulletin_url(year, region, session)

    if type_ == "縣市首長":
        subfolder = "03直轄市長" if "直轄市長" in election_id else "04縣市長"
        return _dir_url(subfolder, roc)

    if type_ == "縣市議員":
        return _council_bulletin_url(type_, year, region)

    if type_ == "鄉鎮市長":
        roc_year = _roc_number(year)
        if roc_year >= 103:
            return f"{_EE_BULLETIN_BASE}/?dir={roc_year}"
        return None

    return None
