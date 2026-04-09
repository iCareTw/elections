import re
from pathlib import Path

import openpyxl

SESSION_YEARS = {
    3: 1995, 4: 1998, 5: 2001,  6: 2004,
    7: 2008, 8: 2012, 9: 2016, 10: 2020, 11: 2024,
}


def _session_from_path(path: Path) -> int:
    m = re.search(r'(\d+)th', path.parent.name)
    return int(m.group(1)) if m else 0


def _county_from_path(path: Path) -> str:
    """從檔名（如 區域_基隆市.xlsx）取出縣市名稱。"""
    stem = path.stem  # e.g. '區域_基隆市'
    if '_' in stem:
        return stem.split('_', 1)[1]
    return stem


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    session = _session_from_path(path)
    year = SESSION_YEARS.get(session, 0)
    county = _county_from_path(path)

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    records = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        area_name, _cand_no, name, _sex, birth_year, party, _tickets, _pct, is_victor = row
        if name is None:
            continue
        if area_name and not str(area_name).startswith(county):
            region = f'{county} {area_name}'
        else:
            region = str(area_name) if area_name else county
        records.append({
            'name': str(name),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'session': session,
            'type': '立法委員',
            'region': region,
            'party': '無黨籍' if not party or party == '無黨籍及未經政黨推薦' else str(party),
            'elected': 1 if is_victor == '*' else 0,
        })
    return records
