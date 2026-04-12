from src.normalize import normalize_name, generate_id


def _year_of(birthday) -> int | None:
    if birthday is None:
        return None
    return int(str(birthday)[:4])


def _build_election(r: dict) -> dict:
    base = {k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}
    if 'session' in r:
        base['session'] = r['session']
    if 'ticket' in r:
        base['ticket'] = r['ticket']
    if 'order_id' in r:
        base['order_id'] = r['order_id']
    return base


def classify_records(records: list[dict], existing: list[dict]) -> dict:
    """
    比對新 records 與現有 candidates，分類為：
    - auto: 可直接處理（action='new' 或 action='merge'）
    - conflicts: 需人工確認

    自動合併條件：name(正規化) + birthday年份 + party 三者皆符合（party 須曾出現於該候選人的任一 election）。
    其餘同名情況均進 conflict。
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

        r_year = _year_of(r['birthday'])
        r_party = r['party']

        # 篩出年份相符的候選人
        if r_year is None:
            year_matches = []
        else:
            year_matches = [c for c in matches if _year_of(c['birthday']) == r_year]

        if not year_matches:
            conflicts.append({'record': r, 'matches': matches})
            continue

        # 在年份相符者中，篩出曾使用相同黨籍的候選人
        party_matches = [
            c for c in year_matches
            if any(e['party'] == r_party for e in c['elections'])
        ]

        if len(party_matches) == 1:
            c = party_matches[0]
            election = _build_election(r)
            if election in c['elections']:
                continue  # 已存在，跳過
            auto.append({'action': 'merge', 'record': r, 'candidate': c})
        else:
            # 換黨、多個符合、或無法唯一識別 → conflict
            conflicts.append({'record': r, 'matches': year_matches})

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
                'birthday': _year_of(r['birthday']),
                'elections': [_build_election(r)],
            })
        elif item['action'] == 'merge':
            c = item['candidate']
            c['elections'].append(_build_election(r))
            c['elections'].sort(key=lambda e: e['year'])

    return result
