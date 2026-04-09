import re
from pathlib import Path

import openpyxl


def filename_to_year(filename: str) -> int:
    """103年直轄市長選舉.xlsx → 2014"""
    m = re.search(r'(\d+)年', filename)
    return int(m.group(1)) + 1911


def normalize_region(region: str) -> str:
    return region.replace('台', '臺')


def parse_workbook(wb: openpyxl.Workbook, year: int) -> list[dict]:
    ws = wb.active
    records = []
    current_region = None

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        region, name, _, _, birth_year, party, _, _, elected_mark, _ = row
        if name is None:
            continue
        if region is not None:
            current_region = normalize_region(str(region))

        records.append({
            'name': str(name),
            'birthday': int(birth_year) if birth_year else None,
            'year': year,
            'type': '縣市首長',
            'region': current_region,
            'party': '無黨籍' if not party or party == '無黨籍及未經政黨推薦' else party,
            'elected': 1 if elected_mark == '*' else 0,
        })
    return records


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    year = filename_to_year(path.name)
    wb = openpyxl.load_workbook(path)
    return parse_workbook(wb, year)
