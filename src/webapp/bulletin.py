from __future__ import annotations

_BULLETIN_BASE = "https://bulletin.cec.gov.tw/?dir=01選舉公報"
_EE_BULLETIN_BASE = "https://eebulletin.cec.gov.tw"

# 直轄市升格時間表
_ALWAYS_DIRECT = {"臺北市", "高雄市"}
_DIRECT_FROM_2010 = {"新北市", "臺中市", "臺南市"}
_DIRECT_FROM_2014 = {"桃園市"}


def _roc(year: int) -> str:
    return f"{year - 1911:03d}年"


def _is_direct_municipality(region: str, year: int) -> bool:
    city = region.split()[0] if region else ""
    if city in _ALWAYS_DIRECT:
        return True
    if city in _DIRECT_FROM_2010 and year >= 2010:
        return True
    if city in _DIRECT_FROM_2014 and year >= 2014:
        return True
    return False


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
        return f"{_BULLETIN_BASE}/01總統副總統/{roc}"

    if type_ == "立法委員":
        folder = f"{roc}第{session}屆" if session else roc
        return f"{_BULLETIN_BASE}/02立法委員/{folder}"

    if type_ == "縣市首長":
        subfolder = "03直轄市長" if _is_direct_municipality(region, year) else "04縣市長"
        return f"{_BULLETIN_BASE}/{subfolder}/{roc}"

    if type_ == "縣市議員":
        subfolder = "05直轄市議員" if _is_direct_municipality(region, year) else "06縣市議員"
        return f"{_BULLETIN_BASE}/{subfolder}/{roc}"

    if type_ == "鄉鎮市長":
        roc_year = year - 1911
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
        return f"{_BULLETIN_BASE}/01總統副總統/{roc}"

    if type_ == "立法委員":
        folder = f"{roc}第{session}屆" if session else roc
        return f"{_BULLETIN_BASE}/02立法委員/{folder}"

    if type_ == "縣市首長":
        subfolder = "03直轄市長" if "直轄市長" in election_id else "04縣市長"
        return f"{_BULLETIN_BASE}/{subfolder}/{roc}"

    if type_ == "縣市議員":
        subfolder = "05直轄市議員" if "直轄市議員" in election_id else "06縣市議員"
        return f"{_BULLETIN_BASE}/{subfolder}/{roc}"

    if type_ == "鄉鎮市長":
        roc_year = year - 1911
        if roc_year >= 103:
            return f"{_EE_BULLETIN_BASE}/?dir={roc_year}"
        return None

    return None
