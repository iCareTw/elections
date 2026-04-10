from pathlib import Path
from src.fetch_legislator import output_path, tickets_url, areas_url

# output_path

def test_output_path_l1():
    assert output_path(11, '區域', '臺北市') == Path('_data/legislator/district-legislator/11th/區域_臺北市.xlsx')

def test_output_path_l1_session3():
    assert output_path(3, '區域', '臺北縣') == Path('_data/legislator/district-legislator/3th/區域_臺北縣.xlsx')

def test_output_path_l2():
    assert output_path(11, '平地原住民') == Path('_data/legislator/district-legislator/11th/平地原住民.xlsx')

def test_output_path_l3():
    assert output_path(9, '山地原住民') == Path('_data/legislator/district-legislator/9th/山地原住民.xlsx')

# tickets_url

def test_tickets_url_l1_city_municipality():
    url = tickets_url('L1', 'abc123', '63', '000', 'A')
    assert url == 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/L0/L1/abc123/A/63_000_00_000_0000.json'

def test_tickets_url_l1_city_county():
    url = tickets_url('L1', 'abc123', '10', '002', 'A')
    assert url == 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/L0/L1/abc123/A/10_002_00_000_0000.json'

def test_tickets_url_l2_national():
    url = tickets_url('L2', 'def456', '00', '000', 'N')
    assert url == 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/L0/L2/def456/N/00_000_00_000_0000.json'

# areas_url

def test_areas_url():
    url = areas_url('abc123')
    assert url == 'https://db.cec.gov.tw/static/elections/data/areas/ELC/L0/L1/abc123/C/00_000_00_000_0000.json'

# write_xlsx

import openpyxl
from src.fetch_legislator import write_xlsx

def test_write_xlsx_creates_file_with_header_and_rows(tmp_path):
    records = [
        {
            'area_name': '臺北市第01選區', 'cand_no': 1, 'cand_name': '吳思瑤',
            'cand_sex': '2', 'cand_birthyear': '1974', 'party_name': '民主進步黨',
            'ticket_num': 91958, 'ticket_percent': 47.22, 'is_victor': '*',
        },
        {
            'area_name': '臺北市第01選區', 'cand_no': 2, 'cand_name': '王某某',
            'cand_sex': '1', 'cand_birthyear': '1970', 'party_name': '中國國民黨',
            'ticket_num': 80000, 'ticket_percent': 41.00, 'is_victor': '',
        },
    ]
    path = tmp_path / '11th' / '區域_臺北市.xlsx'
    write_xlsx(records, path)

    assert path.exists()
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ('地區', '號次', '姓名', '性別', '出生年', '政黨', '得票數', '得票率', '當選')
    assert rows[1][2] == '吳思瑤'
    assert rows[2][2] == '王某某'
    assert len(rows) == 3

# parse_session_map

from src.fetch_legislator import parse_session_map

def test_parse_session_map_extracts_l1_l2_l3():
    raw = [
        {'area_name': '全國', 'theme_items': [
            {'session': 11, 'legislator_type_id': 'L1', 'theme_id': 'aaa', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 11, 'legislator_type_id': 'L2', 'theme_id': 'bbb', 'data_level': 'N', 'legislator_desc': '平地原住民'},
            {'session': 11, 'legislator_type_id': 'L3', 'theme_id': 'ccc', 'data_level': 'N', 'legislator_desc': '山地原住民'},
            {'session': 11, 'legislator_type_id': 'L4', 'theme_id': 'ddd', 'data_level': 'N', 'legislator_desc': '不分區政黨'},
        ]},
    ]
    result = parse_session_map(raw)
    assert (11, 'L1') in result
    assert result[(11, 'L1')] == {'theme_id': 'aaa', 'data_level': 'A', 'desc': '區域'}
    assert (11, 'L2') in result
    assert (11, 'L3') in result
    assert (11, 'L4') not in result  # L4 excluded

def test_parse_session_map_excludes_out_of_range():
    raw = [
        {'area_name': '全國', 'theme_items': [
            {'session': 2,  'legislator_type_id': 'L1', 'theme_id': 'x', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 3,  'legislator_type_id': 'L1', 'theme_id': 'y', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 11, 'legislator_type_id': 'L1', 'theme_id': 'z', 'data_level': 'A', 'legislator_desc': '區域'},
            {'session': 12, 'legislator_type_id': 'L1', 'theme_id': 'w', 'data_level': 'A', 'legislator_desc': '區域'},
        ]},
    ]
    result = parse_session_map(raw)
    assert (2,  'L1') not in result
    assert (3,  'L1') in result
    assert (11, 'L1') in result
    assert (12, 'L1') not in result
