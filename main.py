import argparse
import re
import sys
from pathlib import Path

import yaml

from src.merge import apply_auto, classify_records
from src.normalize import generate_id
from src.parse_mayor import parse_file as parse_mayor
from src.parse_president import parse_file as parse_president
from src.validate import validate_candidates

DATA_DIR = Path('_data')
CANDIDATES_FILE = Path('candidates.yaml')
ELECTION_TYPES_FILE = Path('election_types.yaml')

PARSERS = {
    'president': (parse_president, DATA_DIR / 'president'),
    'mayor':     (parse_mayor,     DATA_DIR / 'mayor'),
}


def _president_year(path: Path) -> int:
    m = re.search(r'第(\d+)任', path.stem)
    if not m:
        return 0
    return 1996 + (int(m.group(1)) - 9) * 4


def _mayor_year(path: Path) -> int:
    m = re.search(r'(\d+)年', path.stem)
    if not m:
        return 0
    return int(m.group(1)) + 1911


def find_xlsx(type_: str, year: int) -> list[Path]:
    _, data_dir = PARSERS[type_]
    files = sorted(data_dir.glob('*.xlsx'))
    if type_ == 'president':
        return [f for f in files if _president_year(f) == year]
    else:
        return [f for f in files if _mayor_year(f) == year]


def load_yaml(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or []


def load_valid_types() -> set[str]:
    data = load_yaml(ELECTION_TYPES_FILE)
    return {t['id'] for t in data}


def resolve_conflicts(conflicts: list[dict], existing: list[dict]) -> list[dict]:
    """互動式處理 conflicts，回傳需要追加至 existing 的新候選人（若選 n）。"""
    to_add = []

    for i, item in enumerate(conflicts, 1):
        r = item['record']
        matches = item['matches']
        print(f'\n\033[33m─── 衝突 {i}/{len(conflicts)} ───────────────────────────────────────\033[0m')
        print(f'新資料：\033[1m{r["name"]}\033[0m  birthday:{r["birthday"]} | {r["type"]} {r["year"]} | {r["party"]} | elected:{r["elected"]}')
        print()
        print('\033[34m現有同名候選人：\033[0m')
        for j, c in enumerate(matches, 1):
            last = c['elections'][-1] if c['elections'] else {}
            print(f'  [{j}] {c["id"]}  生年:{c["birthday"]}  '
                  f'{last.get("type", "")} {last.get("year", "")} ({last.get("party", "")})')

        choices = [str(j) for j in range(1, len(matches) + 1)]
        prompt = f'\n請選擇：{" ".join(f"[{j}]" for j in choices)} 合併  [n] 新增第三人  [s] 跳過 > '
        while True:
            ans = input(prompt).strip().lower()
            if ans in choices:
                c = matches[int(ans) - 1]
                election = {k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')} | ({'ticket': r['ticket']} if 'ticket' in r else {})
                c['elections'].append(election)
                c['elections'].sort(key=lambda e: e['year'])
                if r['birthday'] and c['birthday'] != r['birthday']:
                    print(f'  生年不符：現有 {c["birthday"]}，新資料 {r["birthday"]}')
                    fix = input('  是否以新資料更新 birthday？[y/n] > ').strip().lower()
                    if fix == 'y':
                        c['birthday'] = r['birthday']
                        c['id'] = generate_id(c['name'], c['birthday'])
                break
            elif ans == 'n':
                for m in matches:
                    if m['birthday']:
                        m['id'] = generate_id(m['name'], m['birthday'])
                to_add.append({
                    'name': r['name'],
                    'id': generate_id(r['name'], r['birthday']),
                    'birthday': r['birthday'],
                    'elections': [{k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')} | ({'ticket': r['ticket']} if 'ticket' in r else {})],
                })
                break
            elif ans == 's':
                print('  跳過')
                break

    return to_add


def main():
    parser = argparse.ArgumentParser(description='解析選舉資料並更新 candidates.yaml')
    parser.add_argument('--type', required=True, choices=list(PARSERS.keys()), help='選舉類型')
    parser.add_argument('--year', required=True, type=int, help='西元年份')
    args = parser.parse_args()

    parse_fn, _ = PARSERS[args.type]
    xlsx_files = find_xlsx(args.type, args.year)
    if not xlsx_files:
        print(f'找不到 {args.type} {args.year} 的資料檔', file=sys.stderr)
        sys.exit(1)

    print(f'解析 {len(xlsx_files)} 個檔案 ...')
    records = []
    for f in xlsx_files:
        records.extend(parse_fn(f))
    print(f'共 {len(records)} 筆記錄')

    existing = load_yaml(CANDIDATES_FILE)

    if not existing:
        result = apply_auto(
            [{'action': 'new', 'record': r, 'candidate': None} for r in records],
            []
        )
        print(f'\n首次建立 candidates.yaml，寫入 {len(result)} 筆')
    else:
        classified = classify_records(records, existing)
        auto_count = len(classified['auto'])
        conflict_count = len(classified['conflicts'])

        print(f'\n\033[32m自動合併 {auto_count} 筆\033[0m（無歧義）')
        if conflict_count:
            print(f'\033[33m需人工確認 {conflict_count} 筆\033[0m')

        result = apply_auto(classified['auto'], existing)

        if classified['conflicts']:
            extra = resolve_conflicts(classified['conflicts'], result)
            result.extend(extra)

    valid_types = load_valid_types()
    errors = validate_candidates(result, valid_types)
    if errors:
        print('\n驗證錯誤：', file=sys.stderr)
        for e in errors:
            print(f'  {e}', file=sys.stderr)
        sys.exit(1)

    result.sort(key=lambda c: min((e['year'] for e in c['elections']), default=9999))
    with open(CANDIDATES_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(result, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f'\n\033[32m✓ 寫入 {CANDIDATES_FILE}（共 {len(result)} 筆）\033[0m')


if __name__ == '__main__':
    main()
