from src.merge import classify_records

EXISTING = [
    {
        'name': '柯文哲', 'id': 'id_柯文哲_1959', 'birthday': 1959,
        'elections': [
            {'year': 2014, 'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍', 'elected': 1},
        ]
    },
    {'name': '許淑華', 'id': 'id_許淑華_1973', 'birthday': 1973,
     'elections': [{'year': 2016, 'type': '縣市議員', 'region': '臺北市', 'party': '民主進步黨', 'elected': 1}]},
    {'name': '許淑華', 'id': 'id_許淑華_1975', 'birthday': 1975,
     'elections': [{'year': 2014, 'type': '縣市首長', 'region': '南投縣', 'party': '中國國民黨', 'elected': 0}]},
]


def test_new_person():
    records = [{'name': '吳欣盈', 'birthday': 1978, 'year': 2024,
                'type': '國家元首_總統', 'region': '全國', 'party': '台灣民眾黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 1
    assert result['auto'][0]['action'] == 'new'
    assert len(result['conflicts']) == 0


def test_existing_person_same_party():
    # 柯文哲 + 1959 + 無黨籍 → auto merge
    records = [{'name': '柯文哲', 'birthday': 1959, 'year': 2018,
                'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍', 'elected': 1}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 1
    assert result['auto'][0]['action'] == 'merge'
    assert result['auto'][0]['candidate']['id'] == 'id_柯文哲_1959'


def test_conflict_party_switch():
    # 柯文哲 + 1959 + 台灣民眾黨（新黨）→ conflict
    records = [{'name': '柯文哲', 'birthday': 1959, 'year': 2024,
                'type': '國家元首_總統', 'region': '全國', 'party': '台灣民眾黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['conflicts']) == 1
    assert result['conflicts'][0]['matches'][0]['id'] == 'id_柯文哲_1959'


def test_conflict_year_mismatch():
    # 許淑華 + 1971（不符合 1973 或 1975）→ conflict，matches 為全部同名
    records = [{'name': '許淑華', 'birthday': 1971, 'year': 2024,
                'type': '縣市首長', 'region': '全國', 'party': '民主進步黨', 'elected': 0}]
    result = classify_records(records, EXISTING)
    assert len(result['conflicts']) == 1
    assert len(result['conflicts'][0]['matches']) == 2


def test_conflict_multiple_year_matches():
    # 假設兩個許淑華都是 1973 年（不正常情況，確保 conflict）
    existing_dup = [
        {'name': '許淑華', 'id': 'id_許淑華_1973_a', 'birthday': 1973,
         'elections': [{'year': 2016, 'type': '縣市議員', 'region': '臺北市', 'party': '民主進步黨', 'elected': 1}]},
        {'name': '許淑華', 'id': 'id_許淑華_1973_b', 'birthday': 1973,
         'elections': [{'year': 2018, 'type': '縣市議員', 'region': '臺中市', 'party': '民主進步黨', 'elected': 1}]},
    ]
    records = [{'name': '許淑華', 'birthday': 1973, 'year': 2024,
                'type': '縣市首長', 'region': '全國', 'party': '民主進步黨', 'elected': 0}]
    result = classify_records(records, existing_dup)
    assert len(result['conflicts']) == 1


def test_duplicate_election_skipped():
    records = [{'name': '柯文哲', 'birthday': 1959, 'year': 2014,
                'type': '縣市首長', 'region': '臺北市', 'party': '無黨籍', 'elected': 1}]
    result = classify_records(records, EXISTING)
    assert len(result['auto']) == 0
    assert len(result['conflicts']) == 0
