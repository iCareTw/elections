from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from playwright.sync_api import Page, sync_playwright

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_OUTPUT = Path("_data/province_councilor/1994_province_councilor.yaml")

URLS = [
    {
        "label": "區域",
        "region_override": None,
        "url": "https://db.cec.gov.tw/ElecTable/Election/ElecTickets?dataType=tickets&typeId=ELC&subjectId=T9&legisId=T1&themeId=965dd1723f99ad9dfd4ab25c946533d0&dataLevel=C&prvCode=00&cityCode=000&areaCode=00&deptCode=000&liCode=0000",
    },
    {
        "label": "平地原住民北區",
        "region_override": "平地原住民北區",
        "url": "https://db.cec.gov.tw/ElecTable/Election/ElecTickets?dataType=tickets&typeId=ELC&subjectId=T9&legisId=T2&themeId=fbed043a36b73fb5ef427cb004e546d0&dataLevel=N&prvCode=00&cityCode=000&areaCode=00&deptCode=000&liCode=0000",
    },
    {
        "label": "平地原住民南區",
        "region_override": "平地原住民南區",
        "url": "https://db.cec.gov.tw/ElecTable/Election/ElecTickets?dataType=tickets&typeId=ELC&subjectId=T9&legisId=T2&themeId=0f764b1eaed55ad374d584428688b5c0&dataLevel=N&prvCode=00&cityCode=000&areaCode=00&deptCode=000&liCode=0000",
    },
    {
        "label": "山地原住民",
        "region_override": "山地原住民",
        "url": "https://db.cec.gov.tw/ElecTable/Election/ElecTickets?dataType=tickets&typeId=ELC&subjectId=T9&legisId=T3&themeId=ac7bbdfbcd2c525a4c3ad4d3751d416c&dataLevel=N&prvCode=00&cityCode=000&areaCode=00&deptCode=000&liCode=0000",
    },
]


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _candidate_names(value: str) -> list[str]:
    return [line for line in _lines(value) if not line.startswith("地區")]


def _description_lines(value: str) -> list[str]:
    return [line for line in _lines(value) if line.startswith("地區")]


def _party_name(value: str) -> str:
    if not value or value == "無黨籍及未經政黨推薦":
        return "無黨籍"
    return value


def parse_table_rows(rows: list[list[str]], *, region_override: str | None = None) -> list[dict]:
    records = []
    for row in rows[1:]:
        if len(row) < 8:
            continue

        table_region = row[0].strip()
        names = _candidate_names(row[1])
        descriptions = _description_lines(row[1])
        order_ids = [int(value) for value in _lines(row[2])]
        birth_years = [int(value) for value in _lines(row[4])]
        parties = [_party_name(value) for value in _candidate_names(row[5])]

        count = len(names)
        if not (count == len(order_ids) == len(birth_years) == len(parties) == len(descriptions)):
            raise ValueError(f"欄位數量不一致: {table_region or region_override}")

        for index, name in enumerate(names):
            records.append(
                {
                    "name": name,
                    "birthday": birth_years[index],
                    "order_id": order_ids[index],
                    "party": parties[index],
                    "year": 1994,
                    "region": region_override or table_region,
                    "type": "臺灣省議員",
                    "elected": 1 if "當選" in descriptions[index] else 0,
                }
            )
    return records


def _table_rows(page: Page) -> list[list[str]]:
    page.wait_for_selector("table", timeout=60_000)
    return page.locator("table").nth(0).locator("tr").evaluate_all(
        "(rows) => rows.map((row) => Array.from(row.querySelectorAll('th,td')).map((cell) => cell.innerText))"
    )


def fetch_records(chrome_path: str = DEFAULT_CHROME) -> list[dict]:
    records: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chrome_path)
        try:
            for spec in URLS:
                page = browser.new_page()
                page.goto(spec["url"], wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(2_000)
                records.extend(
                    parse_table_rows(
                        _table_rows(page),
                        region_override=spec["region_override"],
                    )
                )
                page.close()
        finally:
            browser.close()
    return records


def write_yaml(records: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(records, f, allow_unicode=True, sort_keys=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch 1994 Taiwan Provincial Councilor records")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chrome-path", default=DEFAULT_CHROME)
    args = parser.parse_args()

    records = fetch_records(args.chrome_path)
    write_yaml(records, args.output)
    print(f"wrote {args.output} ({len(records)} records)")


if __name__ == "__main__":
    main()
