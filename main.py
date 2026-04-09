import argparse
import re
import sys
from pathlib import Path

import yaml

from src.merge import apply_auto, classify_records
from src.normalize import generate_id
from src.parse_legislator import parse_file as parse_legislator
from src.parse_mayor import parse_file as parse_mayor
from src.parse_president import parse_file as parse_president
from src.validate import validate_candidates

DATA_DIR = Path('_data')
CANDIDATES_FILE = Path('candidates.yaml')
ELECTION_TYPES_FILE = Path('election_types.yaml')

PARSERS = {
    'president':  (parse_president,  DATA_DIR / 'president'),
    'mayor':      (parse_mayor,      DATA_DIR / 'mayor'),
    'legislator': (parse_legislator, DATA_DIR / 'legislator'),
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


def find_xlsx(type_: str, year: int = 0, session: int = 0) -> list[Path]:
    _, data_dir = PARSERS[type_]
    if type_ == 'legislator':
        return sorted((data_dir / f'{session}th').glob('*.xlsx'))
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


def _make_election(r: dict) -> dict:
    base = {k: r[k] for k in ('year', 'type', 'region', 'party', 'elected')}
    if 'session' in r:
        base['session'] = r['session']
    if 'ticket' in r:
        base['ticket'] = r['ticket']
    return base


def _add_as_new(r: dict, matches: list[dict], to_add: list[dict]) -> None:
    """將 r 新增為獨立候選人，並更新現有同名者的 id（加上生日後綴）。"""
    for m in matches:
        if m['birthday']:
            m['id'] = generate_id(m['name'], m['birthday'])
    to_add.append({
        'name': r['name'],
        'id': generate_id(r['name'], r['birthday']),
        'birthday': r['birthday'],
        'elections': [_make_election(r)],
    })


def _resolve_birthday(c: dict, r: dict) -> None:
    """當生日不同時，互動式詢問要以哪個生日為主。"""
    print(f'  生年不同：現有 \033[1m{c["birthday"]}\033[0m，新資料 \033[1m{r["birthday"]}\033[0m')
    while True:
        ans = input('  以哪個為主？[1] 保留現有  [2] 採用新資料  [m] 手動輸入 > ').strip().lower()
        if ans == '1':
            break
        elif ans == '2':
            c['birthday'] = r['birthday']
            c['id'] = generate_id(c['name'], c['birthday'])
            break
        elif ans == 'm':
            val = input('  請輸入生日（yyyy 或 yyyy/mm 或 yyyy/mm/dd）> ').strip()
            if val:
                c['birthday'] = val
                c['id'] = generate_id(c['name'], c['birthday'])
            break


def _fmt_elected(elected) -> str:
    return '\033[32m當選\033[0m' if elected == 1 else '未當選'


def _fmt_election_label(e: dict) -> str:
    """立法委員加屆次，其他只顯示 type + year。"""
    session = e.get('session')
    if session:
        return f'{e["type"]}  第{session}屆 ({e["year"]})'
    return f'{e["type"]}  {e["year"]}'


def _print_election_fields(e: dict, indent: str = '    ') -> None:
    """以統一縮排輸出一筆選舉的所有欄位。"""
    print(f'{indent}選舉    {_fmt_election_label(e)}')
    print(f'{indent}地區    {e.get("region") or "不詳"}')
    print(f'{indent}政黨    {e["party"]}')
    print(f'{indent}結果    {_fmt_elected(e["elected"])}')
    if e.get('ticket'):
        print(f'{indent}搭檔    {e["ticket"]}')


def _print_conflict_panel(r: dict, matches: list[dict]) -> None:
    bday_new = r['birthday']

    # 新資料
    bday_str = str(bday_new) if bday_new else '不詳'
    print(f'  \033[36m新資料\033[0m')
    print(f'    生年    {bday_str}')
    _print_election_fields(r)

    # 現有候選人
    for j, c in enumerate(matches, 1):
        label = f'現有 [{j}]' if len(matches) > 1 else '現有'
        bday_diff = bool(bday_new and c['birthday'] and bday_new != c['birthday'])
        warn = '  \033[33m⚠️  與新資料不同\033[0m' if bday_diff else ''
        bday_str_c = str(c['birthday']) if c['birthday'] else '不詳'
        print()
        print(f'  \033[34m{label}\033[0m  {c["id"]}')
        print(f'    生年    {bday_str_c}{warn}')
        if c['elections']:
            for k, e in enumerate(c['elections']):
                if k > 0:
                    print(f'    {"─" * 30}')
                _print_election_fields(e)
        else:
            print(f'    選舉    （無選舉紀錄）')

    print()


def resolve_conflicts(conflicts: list[dict], existing: list[dict]) -> list[dict]:
    """互動式處理 conflicts，回傳需要追加至 existing 的新候選人。"""
    to_add = []

    for i, item in enumerate(conflicts, 1):
        r = item['record']
        matches = item['matches']
        print(f'\n\033[33m─── 衝突 {i}/{len(conflicts)} ───────────────────────────────────────\033[0m')
        _print_conflict_panel(r, matches)

        if len(matches) == 1:
            # 單一同名者：先問是否同人
            while True:
                ans = input('\n是否為同一人？[y] 是  [n] 新增為不同人  [s] 跳過 > ').strip().lower()
                if ans == 'y':
                    c = matches[0]
                    c['elections'].append(_make_election(r))
                    c['elections'].sort(key=lambda e: e['year'])
                    if r['birthday'] and c['birthday'] != r['birthday']:
                        _resolve_birthday(c, r)
                    elif r['birthday'] and not c['birthday']:
                        upd = input(f'  現有生年為空，是否補上 {r["birthday"]}？[y/n] > ').strip().lower()
                        if upd == 'y':
                            c['birthday'] = r['birthday']
                            c['id'] = generate_id(c['name'], c['birthday'])
                    break
                elif ans == 'n':
                    _add_as_new(r, matches, to_add)
                    break
                elif ans == 's':
                    print('  跳過')
                    break
        else:
            # 多個同名者：選擇合併哪一個，或新增
            choices = [str(j) for j in range(1, len(matches) + 1)]
            prompt = f'\n請選擇：{" ".join(f"[{j}]" for j in choices)} 合併  [n] 新增為不同人  [s] 跳過 > '
            while True:
                ans = input(prompt).strip().lower()
                if ans in choices:
                    c = matches[int(ans) - 1]
                    c['elections'].append(_make_election(r))
                    c['elections'].sort(key=lambda e: e['year'])
                    if r['birthday'] and c['birthday'] != r['birthday']:
                        _resolve_birthday(c, r)
                    elif r['birthday'] and not c['birthday']:
                        upd = input(f'  現有生年為空，是否補上 {r["birthday"]}？[y/n] > ').strip().lower()
                        if upd == 'y':
                            c['birthday'] = r['birthday']
                            c['id'] = generate_id(c['name'], c['birthday'])
                    break
                elif ans == 'n':
                    _add_as_new(r, matches, to_add)
                    break
                elif ans == 's':
                    print('  跳過')
                    break

    return to_add


def main():
    parser = argparse.ArgumentParser(description='解析選舉資料並更新 candidates.yaml')
    parser.add_argument('--type', required=True, choices=list(PARSERS.keys()), help='選舉類型')
    parser.add_argument('--year', type=int, help='西元年份 (president/mayor)')
    parser.add_argument('--session', type=int, help='屆次 (legislator)')
    args = parser.parse_args()

    if args.type == 'legislator':
        if not args.session:
            print('--type legislator 需要 --session', file=sys.stderr)
            sys.exit(1)
    else:
        if not args.year:
            print(f'--type {args.type} 需要 --year', file=sys.stderr)
            sys.exit(1)

    parse_fn, _ = PARSERS[args.type]
    xlsx_files = find_xlsx(args.type, year=args.year or 0, session=args.session or 0)
    if not xlsx_files:
        label = f'session {args.session}' if args.type == 'legislator' else str(args.year)
        print(f'找不到 {args.type} {label} 的資料檔', file=sys.stderr)
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
