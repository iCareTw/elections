from src.merge import classify_records

EXISTING = [
    {
        'name': '柯文哲', 'id': 'id_柯文哲', 'birthday': 1959,
        'elections': [
            {'year': 2014, 'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍', 'elected': 1},
        ]
    },
    {'name': '許淑華', 'id': 'id_許淑華_1973', 'birthday': 1973, 'elections': []},
    {'name': '許淑華', 'id': 'id_許淑華_1975', 'birthday': 1975, 'elections': []},
]


def test_new_person():
    records = [{'name': '吳欣盈', 'birthday': 1978, 'year': 2024,
                'type': '國家元首', 'region': None, 'party': '台灣民眾黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 1
    assert result['auto'][0]['action'] == 'new'
    assert len(result['conflicts']) == 0


def test_existing_person_new_election():
    records = [{'name': '柯文哲', 'birthday': 1959, 'year': 2024,
                'type': '國家元首', 'region': None, 'party': '台灣民眾黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 1
    assert result['auto'][0]['action'] == 'merge'
    assert result['auto'][0]['candidate']['id'] == 'id_柯文哲'


def test_conflict_multiple_same_name():
    records = [{'name': '許淑華', 'birthday': 1971, 'year': 2024,
                'type': '國家元首', 'region': None, 'party': '民主進步黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['conflicts']) == 1
    assert len(result['conflicts'][0]['matches']) == 2


def test_duplicate_election_skipped():
    records = [{'name': '柯文哲', 'birthday': 1959, 'year': 2014,
                'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍', 'elected': 1}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 0
    assert len(result['conflicts']) == 0
