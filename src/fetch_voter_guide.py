"""
Scrape 選舉公報 PDFs from bulletin.cec.gov.tw and eebulletin.cec.gov.tw.

Usage:
    uv run python -m src.fetch_voter_guide [--force] [--concurrency 4]
    uv run python -m src.fetch_voter_guide --site bulletin --force
    uv run python -m src.fetch_voter_guide --site eebulletin
"""

import asyncio
import argparse
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import httpx
from playwright.async_api import async_playwright, Page

DATA_ROOT = Path('_data/voter_guide')

BULLETIN_BASE = 'https://bulletin.cec.gov.tw'
EEBULLETIN_BASE = 'https://eebulletin.cec.gov.tw'

LEGIS_SUB_MAP = {
    '01區域': 'district',
    '02全國不分區及僑居國外國民': 'party',
    '03平地山地原住民': 'native',
    '04補選': 'by-election',
}


def _parse_year(s: str) -> str:
    m = re.match(r'(\d+)年', s)
    return m.group(1) if m else s


def _parse_legis_session(s: str) -> str:
    """'105年第9屆' → '09th_105', '113年第11屆' → '11th_113'."""
    m = re.match(r'(\d+)年第(\d+)屆', s)
    if not m:
        return s
    year, nth = m.group(1), m.group(2)
    return f'{int(nth):02d}th_{year}'


def bulletin_pdf_to_local(pdf_url: str) -> Path | None:
    """Map a bulletin.cec.gov.tw PDF URL to a local path. Returns None if unmapped."""
    raw_path = unquote(urlparse(pdf_url).path).strip('/')
    parts = raw_path.split('/')
    if parts and parts[0] == '01選舉公報':
        parts = parts[1:]
    if len(parts) < 2:
        return None

    type_dir = parts[0]
    filename = parts[-1]
    middle = parts[1:-1]

    match type_dir:
        case '01總統副總統':
            return DATA_ROOT / 'president' / filename

        case '02立法委員':
            if len(middle) < 2:
                return None
            session = _parse_legis_session(middle[0])
            sub_orig = middle[1]
            sub = LEGIS_SUB_MAP.get(sub_orig, sub_orig)
            path = DATA_ROOT / 'legislator' / session / sub
            for seg in middle[2:]:
                path /= seg
            return path / filename

        case '03直轄市長' | '04縣市長':
            if not middle:
                return None
            year = _parse_year(middle[0])
            # Flatten: skip all intermediate dirs (county, 01紙本公報, etc.)
            return DATA_ROOT / 'mayor' / year / filename

        case '05直轄市議員' | '06縣市議員':
            if not middle:
                return None
            year = _parse_year(middle[0])
            path = DATA_ROOT / 'councilor' / year
            for seg in middle[1:]:
                path /= seg
            return path / filename

        case '07省長':
            return DATA_ROOT / 'province' / filename

        case '08省議員':
            if not middle:
                return None
            year = _parse_year(middle[0])
            return DATA_ROOT / 'province_councilor' / year / filename

        case '09國大代表':
            if not middle:
                return None
            year = _parse_year(middle[0])
            path = DATA_ROOT / 'mna' / year
            for seg in middle[1:]:
                path /= seg
            return path / filename

    return None


def eebulletin_pdf_to_local(pdf_url: str) -> Path | None:
    """Map an eebulletin.cec.gov.tw PDF URL to a local path. Returns None if irrelevant."""
    raw_path = unquote(urlparse(pdf_url).path).strip('/')
    parts = raw_path.split('/')
    if len(parts) < 4:
        return None

    year, county, category = parts[0], parts[1], parts[2]
    rest = parts[3:]
    filename = rest[-1]
    middle = rest[:-1]

    match category:
        case '05村里長':
            path = DATA_ROOT / 'village' / year / county
            for seg in middle:
                path /= seg
            return path / filename
        case '03原住民區長':
            return DATA_ROOT / 'indigenous_chief' / year / county / filename
        case '04原住民區民代表':
            return DATA_ROOT / 'indigenous_rep' / year / county / filename

    return None


# bulletin: skip 有聲公報 and 罷免案 directories
_BULLETIN_SKIP = frozenset(['有聲公報', '罷免案'])

# eebulletin: only enter these categories under each county
_EEBULLETIN_WANTED = frozenset(['03原住民區長', '04原住民區民代表', '05村里長'])


def _bulletin_skip_dir(href: str) -> bool:
    decoded = unquote(href[5:])  # strip '?dir='
    return any(seg in _BULLETIN_SKIP for seg in decoded.split('/'))


def _eebulletin_skip_dir(href: str) -> bool:
    parts = unquote(href[5:]).split('/')
    # At category depth (year/county/category), only enter wanted categories
    return len(parts) >= 3 and parts[2] not in _EEBULLETIN_WANTED


async def _crawl(
    page: Page,
    url: str,
    visited: set[str],
    pdf_urls: list[str],
    skip_dir=None,
) -> None:
    if url in visited:
        return
    visited.add(url)

    print(f'  scan {url}')
    try:
        await page.goto(url, timeout=30_000)
        await page.wait_for_selector('main a', timeout=15_000)
    except Exception as e:
        print(f'  WARN {url}: {e}')
        return

    anchors = await page.query_selector_all('main a[href]')
    dir_links: list[str] = []

    for anchor in anchors:
        href = await anchor.get_attribute('href')
        if not href or href.startswith('#'):
            continue
        if href.lower().endswith('.pdf'):
            pdf_urls.append(urljoin(url, href))
        elif href.startswith('?dir='):
            if skip_dir is None or not skip_dir(href):
                dir_links.append(urljoin(url, href))

    for link in dir_links:
        await asyncio.sleep(0.2)
        await _crawl(page, link, visited, pdf_urls, skip_dir)


async def _download_all(pdf_urls: list[str], mapper, force: bool, concurrency: int) -> None:
    semaphore = asyncio.Semaphore(concurrency)
    skipped = 0
    saved = 0
    errors = 0

    async def _one(client: httpx.AsyncClient, url: str) -> None:
        nonlocal skipped, saved, errors
        local = mapper(url)
        if local is None:
            return
        if local.exists() and not force:
            skipped += 1
            return
        async with semaphore:
            try:
                r = await client.get(url, follow_redirects=True)
                r.raise_for_status()
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(r.content)
                saved += 1
                print(f'  saved {local}')
                await asyncio.sleep(1)
            except Exception as e:
                errors += 1
                print(f'  ERROR {url}: {e}')

    async with httpx.AsyncClient(timeout=60, verify=False) as client:
        await asyncio.gather(*[_one(client, u) for u in pdf_urls])

    print(f'  done: saved={saved}, skipped={skipped}, errors={errors}')


async def run(site: str | None, force: bool, concurrency: int) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()

        if site in (None, 'bulletin'):
            print('\n=== bulletin.cec.gov.tw ===')
            pdf_urls: list[str] = []
            await _crawl(
                page,
                f'{BULLETIN_BASE}/?dir=01%E9%81%B8%E8%88%89%E5%85%AC%E5%A0%B1',
                set(),
                pdf_urls,
                skip_dir=_bulletin_skip_dir,
            )
            print(f'Found {len(pdf_urls)} PDFs, downloading...')
            await _download_all(pdf_urls, bulletin_pdf_to_local, force, concurrency)

        if site in (None, 'eebulletin'):
            print('\n=== eebulletin.cec.gov.tw ===')
            pdf_urls = []
            await _crawl(
                page,
                f'{EEBULLETIN_BASE}/',
                set(),
                pdf_urls,
                skip_dir=_eebulletin_skip_dir,
            )
            print(f'Found {len(pdf_urls)} PDFs, downloading...')
            await _download_all(pdf_urls, eebulletin_pdf_to_local, force, concurrency)

        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Scrape 選舉公報 PDFs')
    parser.add_argument('--site', choices=['bulletin', 'eebulletin'], help='scrape only one site')
    parser.add_argument('--force', action='store_true', help='overwrite existing files')
    parser.add_argument('--concurrency', type=int, default=4, help='parallel download workers (default: 4)')
    args = parser.parse_args()
    asyncio.run(run(args.site, args.force, args.concurrency))


if __name__ == '__main__':
    main()
