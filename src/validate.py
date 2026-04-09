def validate_candidates(candidates: list[dict], valid_types: set[str]) -> list[str]:
    errors = []
    seen_ids = {}

    for c in candidates:
        cid = c.get('id', '')
        if cid in seen_ids:
            errors.append(f"重複 ID: {cid} ({seen_ids[cid]} 與 {c['name']})")
        seen_ids[cid] = c['name']

        years = [e['year'] for e in c.get('elections', [])]
        if years != sorted(years):
            errors.append(f"{c['name']} ({cid}): elections 未依 year 升冪排序")

        for e in c.get('elections', []):
            if e['type'] not in valid_types:
                errors.append(f"{c['name']} ({cid}): 未知 type '{e['type']}'")

    return errors
