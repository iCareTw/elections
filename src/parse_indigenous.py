from pathlib import Path

import openpyxl

from src.normalize import decode_cec_name


def _parse(path: str | Path, election_type: str) -> list[dict]:
    path = Path(path)
    year = int(path.parent.name)
    city = path.stem

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    records = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        area_name, _cand_no, name, _sex, birth_year, party, _tickets, _pct, is_victor = row
        if name is None:
            continue
        records.append({
            'name': decode_cec_name(str(name)),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': election_type,
            'region': f'{city} {area_name}',
            'party': '無黨籍' if not party or party == '無黨籍及未經政黨推薦' else str(party),
            'elected': 1 if is_victor == '*' else 0,
        })
    return records


def parse_chief_file(path: str | Path) -> list[dict]:
    return _parse(path, '原住民區長')


def parse_rep_file(path: str | Path) -> list[dict]:
    return _parse(path, '原住民區民代表')
