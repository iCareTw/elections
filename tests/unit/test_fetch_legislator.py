from pathlib import Path
from src.fetch_legislator import output_path, tickets_url, areas_url

# output_path

def test_output_path_l1():
    assert output_path(11, '區域', '臺北市') == Path('_data/legislator/11th/區域_臺北市.xlsx')

def test_output_path_l1_session3():
    assert output_path(3, '區域', '臺北縣') == Path('_data/legislator/3th/區域_臺北縣.xlsx')

def test_output_path_l2():
    assert output_path(11, '平地原住民') == Path('_data/legislator/11th/平地原住民.xlsx')

def test_output_path_l3():
    assert output_path(9, '山地原住民') == Path('_data/legislator/9th/山地原住民.xlsx')

# tickets_url

def test_tickets_url_l1_city():
    url = tickets_url('L1', 'abc123', '63', 'A')
    assert url == 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/L0/L1/abc123/A/63_000_00_000_0000.json'

def test_tickets_url_l2_national():
    url = tickets_url('L2', 'def456', '00', 'N')
    assert url == 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/L0/L2/def456/N/00_000_00_000_0000.json'

# areas_url

def test_areas_url():
    url = areas_url('abc123')
    assert url == 'https://db.cec.gov.tw/static/elections/data/areas/ELC/L0/L1/abc123/C/00_000_00_000_0000.json'
