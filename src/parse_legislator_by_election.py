import re
from pathlib import Path

import openpyxl


def _session_from_path(path: Path) -> int:
    match = re.search(r"(\d+)th", path.parent.name)
    return int(match.group(1)) if match else 0


def _year_from_vote_date(vote_date: object) -> int | None:
    if vote_date is None:
        return None
    match = re.match(r"(\d{4})-", str(vote_date))
    return int(match.group(1)) if match else None


def _region_from_path(path: Path) -> str:
    stem = path.stem
    match = re.search(r"立法委員(.+?)(?:缺額)?補選$", stem)
    return match.group(1) if match else stem


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    session = _session_from_path(path)
    region = _region_from_path(path)

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))[1:]
    victor_marked = any(row[9] == "*" for row in rows)
    max_ticket = max((int(row[7]) for row in rows if row[7] is not None), default=None)
    records = []

    for row in rows:
        vote_date, _area_name, _cand_no, name, _sex, birth_year, party, _tickets, _pct, is_victor = row
        if name is None:
            continue
        elected = is_victor == "*" if victor_marked else _tickets is not None and int(_tickets) == max_ticket
        records.append({
            "name": str(name),
            "birthday": int(birth_year) if birth_year else None,
            "year": _year_from_vote_date(vote_date),
            "session": session,
            "type": "立法委員",
            "region": region,
            "party": "無黨籍" if not party or party == "無黨籍及未經政黨推薦" else str(party),
            "elected": 1 if elected else 0,
        })
    return records
