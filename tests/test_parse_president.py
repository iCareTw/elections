import openpyxl
from src.parse_president import parse_workbook, filename_to_year


def make_wb(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    return wb


def test_filename_to_year():
    assert filename_to_year("第16任總統副總統選舉.xlsx") == 2024
    assert filename_to_year("第14任總統副總統選舉.xlsx") == 2016
    assert filename_to_year("第10任總統副總統選舉.xlsx") == 2000


def test_parse_single_pair():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('全國', '賴清德', 2, '男', '1959', '民主進步黨', '5,586,019', '40.05%', '*', '是'),
        (None,   '蕭美琴', None, '女', '1971', None, None, None, None, None),
    ])
    records = parse_workbook(wb, year=2024)
    assert len(records) == 2
    assert records[0] == {
        'name': '賴清德', 'birthday': 1959, 'year': 2024,
        'type': '國家元首', 'region': '全國',
        'party': '民主進步黨', 'elected': 1,
    }
    assert records[1] == {
        'name': '蕭美琴', 'birthday': 1971, 'year': 2024,
        'type': '國家元首', 'region': '全國',
        'party': '民主進步黨', 'elected': 1,
    }


def test_parse_losing_candidate():
    wb = make_wb([
        ('地區', '姓名', '號次', '性別', '出生年次', '推薦政黨', '得票數', '得票率', '當選', '現任'),
        ('全國', '侯友宜', 3, '男', '1957', '中國國民黨', '4,671,021', '33.49%', ' ', None),
        (None,   '趙少康', None, '男', '1950', None, None, None, None, None),
    ])
    records = parse_workbook(wb, year=2024)
    assert records[0]['elected'] == 0
    assert records[1]['elected'] == 0
    assert records[1]['party'] == '中國國民黨'
