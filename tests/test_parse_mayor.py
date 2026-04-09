import openpyxl
from src.parse_mayor import parse_workbook, filename_to_year, normalize_region


def make_wb(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    return wb


def test_filename_to_year():
    assert filename_to_year("111年直轄市長選舉.xlsx") == 2022
    assert filename_to_year("103年縣市長選舉.xlsx") == 2014


def test_normalize_region():
    assert normalize_region("臺北市") == "臺北市"
    assert normalize_region("台北市") == "臺北市"
    assert normalize_region("台中市") == "臺中市"


def test_parse_basic():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('臺北市', '蔣萬安', 6, '男', '1978', '中國國民黨', '575,590', '42.29%', '*', None),
        (None,    '黃珊珊', 8, '女', '1969', '無黨籍及未經政黨推薦', '342,141', '25.14%', ' ', None),
    ])
    records = parse_workbook(wb, year=2022)
    assert len(records) == 2
    assert records[0] == {
        'name': '蔣萬安', 'birthday': 1978, 'year': 2022,
        'type': '縣市首長', 'region': '臺北市',
        'party': '中國國民黨', 'elected': 1,
    }
    assert records[1]['region'] == '臺北市'
    assert records[1]['elected'] == 0


def test_region_carries_across_rows():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('新北市', '候選人A', 1, '男', '1970', '民主進步黨', '100', '50%', '*', None),
        (None,    '候選人B', 2, '男', '1975', '中國國民黨', '100', '50%', ' ', None),
        ('臺中市', '候選人C', 1, '女', '1980', '民主進步黨', '200', '60%', '*', None),
    ])
    records = parse_workbook(wb, year=2022)
    assert records[0]['region'] == '新北市'
    assert records[1]['region'] == '新北市'
    assert records[2]['region'] == '臺中市'
