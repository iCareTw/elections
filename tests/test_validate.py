from src.validate import validate_candidates

VALID_TYPES = {'國家元首', '縣市首長', '立法委員', '縣市議員'}


def test_valid_passes():
    candidates = [{
        'name': '柯文哲', 'id': 'id_柯文哲', 'birthday': 1959,
        'elections': [
            {'year': 2014, 'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍', 'elected': 1},
            {'year': 2024, 'type': '國家元首', 'region': None, 'party': '台灣民眾黨', 'elected': 0},
        ]
    }]
    assert validate_candidates(candidates, VALID_TYPES) == []


def test_invalid_type():
    candidates = [{'name': 'X', 'id': 'id_X', 'birthday': None,
        'elections': [{'year': 2024, 'type': '未知類型', 'region': None, 'party': 'A', 'elected': 0}]}]
    errors = validate_candidates(candidates, VALID_TYPES)
    assert any('未知類型' in e for e in errors)


def test_elections_not_sorted():
    candidates = [{'name': 'X', 'id': 'id_X', 'birthday': None,
        'elections': [
            {'year': 2024, 'type': '國家元首', 'region': None, 'party': 'A', 'elected': 0},
            {'year': 2018, 'type': '縣市首長', 'region': '臺北市', 'party': 'B', 'elected': 1},
        ]}]
    errors = validate_candidates(candidates, VALID_TYPES)
    assert any('排序' in e for e in errors)


def test_duplicate_ids():
    candidates = [
        {'name': 'X', 'id': 'id_X', 'birthday': None, 'elections': []},
        {'name': 'Y', 'id': 'id_X', 'birthday': None, 'elections': []},
    ]
    errors = validate_candidates(candidates, VALID_TYPES)
    assert any('id_X' in e for e in errors)
