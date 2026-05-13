from pathlib import Path

import openpyxl


def _parse_filepath(path: Path) -> tuple[int, str | None]:
    """Returns (year, city) parsed from parent dir and filename."""
    year = int(path.parent.name)
    parts = path.stem.split('_', 2)  # ['直轄市議員', '區域', '臺北市'] or ['直轄市議員', '原住民']
    city = parts[2] if len(parts) > 2 else None
    return year, city


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    year, city = _parse_filepath(path)

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    records = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        area_name, _cand_no, name, _sex, birth_year, party, _tickets, _pct, is_victor = row
        if name is None:
            continue
        if city and area_name and not str(area_name).startswith(city):
            region = f'{city} {area_name}'
        else:
            region = str(area_name) if area_name else (city or '')
        records.append({
            'name': str(name),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': '縣市議員',
            'region': region,
            'party': '無黨籍' if not party or party == '無黨籍及未經政黨推薦' else str(party),
            'elected': 1 if is_victor == '*' else 0,
        })
    return records
