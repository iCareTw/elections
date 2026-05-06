from __future__ import annotations

_BULLETIN_BASE = "https://bulletin.cec.gov.tw/?dir=01選舉公報"
_EE_BULLETIN_BASE = "https://eebulletin.cec.gov.tw"


def _roc(year: int) -> str:
    return f"{year - 1911:03d}年"


def bulletin_url(payload: dict, election_id: str) -> str | None:
    """
    根據 payload 與 election_id 產生中選會選舉公報的目錄連結。
    連結指向年份層（或立委的屆次層），使用者點進後再找縣市即可。
    回傳 None 表示該選舉類型無公報可查。
    """
    type_ = payload.get("type", "")
    year = payload.get("year")
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
        return None  # 早期鄉鎮市長公報未數位化

    return None
