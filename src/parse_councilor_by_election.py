import re
from pathlib import Path

import openpyxl

_TYPE_MAP = {
    "T1": "直轄市議員",
    "T2": "縣市議員",
}


def _type_from_path(path: Path) -> str:
    return _TYPE_MAP.get(path.parent.name, "縣市議員")


def _year_from_vote_date(vote_date: object) -> int | None:
    if vote_date is None:
        return None
    match = re.match(r"(\d{4})-", str(vote_date))
    return int(match.group(1)) if match else None


def _region_from_stem(stem: str) -> str:
    # "臺中市議會第4屆議員第15選舉區缺額補選" → "臺中市 第15選舉區"
    m = re.match(r"^(.{2,4}(?:市|縣)).*?(第\d+選舉區)", stem)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m2 = re.match(r"^(.{2,4}(?:市|縣))", stem)
    return m2.group(1) if m2 else stem


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    election_type = _type_from_path(path)
    region = _region_from_stem(path.stem)

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))[1:]
    victor_marked = any(row[9] == "*" for row in rows if row[9] is not None)
    max_ticket = max((int(row[7]) for row in rows if row[7] is not None), default=None)
    records = []

    for row in rows:
        vote_date, _area, _no, name, _sex, birth_year, party, tickets, _pct, is_victor = row
        if name is None:
            continue
        elected = is_victor == "*" if victor_marked else tickets is not None and int(tickets) == max_ticket
        records.append({
            "name": str(name),
            "birthyear": int(birth_year) if birth_year else None,
            "year": _year_from_vote_date(vote_date),
            "type": election_type,
            "region": region,
            "party": "無黨籍" if not party or party == "無黨籍及未經政黨推薦" else str(party),
            "elected": 1 if elected else 0,
        })
    return records
