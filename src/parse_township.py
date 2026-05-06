from pathlib import Path

import openpyxl


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    year = int(path.parent.name)
    county = path.stem  # e.g. 宜蘭縣

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    records = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        area_name, _cand_no, name, _sex, birth_year, party, _tickets, _pct, is_victor = row
        if name is None:
            continue
        township = str(area_name) if area_name else county
        records.append({
            'name': str(name),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': '鄉鎮市長',
            'region': f'{county} {township}',
            'party': '無黨籍' if not party or party == '無黨籍及未經政黨推薦' else str(party),
            'elected': 1 if is_victor == '*' else 0,
        })
    return records
