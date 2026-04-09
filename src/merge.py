from src.normalize import normalize_name, generate_id


def _build_election(r: dict) -> dict:
    base = {k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}
    if 'session' in r:
        base['session'] = r['session']
    if 'ticket' in r:
        base['ticket'] = r['ticket']
    return base


def classify_records(records: list[dict], existing: list[dict]) -> dict:
    """
    比對新 records 與現有 candidates，分類為：
    - auto: 可直接處理（action='new' 或 action='merge'）
    - conflicts: 需人工確認（同名多人，或 birthday 不符）
    """
    index: dict[str, list[dict]] = {}
    for c in existing:
        norm = normalize_name(c['name'])
        index.setdefault(norm, []).append(c)

    auto = []
    conflicts = []

    for r in records:
        norm = normalize_name(r['name'])
        matches = index.get(norm, [])

        if not matches:
            auto.append({'action': 'new', 'record': r, 'candidate': None})
            continue

        if len(matches) == 1:
            c = matches[0]
            bday_match = (r['birthday'] is not None and c['birthday'] is not None
                          and r['birthday'] == c['birthday'])
            if bday_match:
                election = _build_election(r)
                if election in c['elections']:
                    continue  # 已存在，跳過
                auto.append({'action': 'merge', 'record': r, 'candidate': c})
            else:
                conflicts.append({'record': r, 'matches': matches})
            continue

        conflicts.append({'record': r, 'matches': matches})

    return {'auto': auto, 'conflicts': conflicts}


def apply_auto(auto: list[dict], existing: list[dict]) -> list[dict]:
    """將 auto 結果套用至 existing，回傳更新後的 list。"""
    result = list(existing)

    for item in auto:
        r = item['record']
        if item['action'] == 'new':
            result.append({
                'name': r['name'],
                'id': generate_id(r['name'], r['birthday']),
                'birthday': r['birthday'],
                'elections': [_build_election(r)],
            })
        elif item['action'] == 'merge':
            c = item['candidate']
            c['elections'].append(_build_election(r))
            c['elections'].sort(key=lambda e: e['year'])

    return result
