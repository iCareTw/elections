from pathlib import Path

import openpyxl

from src.normalize import decode_cec_name


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    year = int(path.parent.name)
    # filename may be "desc_county.xlsx" (session 99) or "county.xlsx"
    stem = path.stem
    county = stem.split('_', 1)[-1] if '_' in stem else stem

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    records = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        area_name, _cand_no, name, _sex, birth_year, party, _tickets, _pct, is_victor = row
        if name is None:
            continue
        village = str(area_name) if area_name else county
        records.append({
            'name': decode_cec_name(str(name)),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': '村里長',
            'region': f'{county} {village}',
            'party': '無黨籍' if not party or party == '無黨籍及未經政黨推薦' else str(party),
            'elected': 1 if is_victor == '*' else 0,
        })
    return records
