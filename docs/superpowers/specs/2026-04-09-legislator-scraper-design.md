# Legislator Scraper Design

## Goal

Scrape district legislator (區域立委), plains indigenous (平地原住民), and mountain indigenous (山地原住民) election data from the CEC database for sessions 3–11, saving each as an XLSX file.

## Background

The CEC website (`db.cec.gov.tw`) is a Nuxt SPA. All data is served as static JSON files — no browser automation is needed. The XLSX files shown on the site are generated client-side from this JSON. We replicate that by writing the JSON records directly to XLSX using `openpyxl`.

## Output Structure

```
_data/legislator/
  {session}th/
    區域_{area_name}.xlsx    # one file per city/county, sessions 3–11
    平地原住民.xlsx           # one file per session
    山地原住民.xlsx           # one file per session
```

Example for session 11:

```
_data/legislator/11th/
  區域_臺北市.xlsx
  區域_新北市.xlsx
  ...
  平地原住民.xlsx
  山地原住民.xlsx
```

## API Endpoints

Base URL: `https://db.cec.gov.tw`

| Purpose          | URL pattern                                                                              |
|------------------|------------------------------------------------------------------------------------------|
| Session index    | `/static/elections/list/ELC_L0.json`                                                     |
| City list (L1)   | `/static/elections/data/areas/ELC/L0/L1/{themeId}/C/00_000_00_000_0000.json`            |
| City tickets (L1)| `/static/elections/data/tickets/ELC/L0/L1/{themeId}/A/{prvCode}_000_00_000_0000.json`   |
| Indigenous (L2/3)| `/static/elections/data/tickets/ELC/L0/{legisId}/{themeId}/N/00_000_00_000_0000.json`   |

`themeId` and `legisId` are fetched dynamically from the session index at runtime.

## XLSX Schema

Each row is one candidate record. Columns:

| Column           | Source field      |
|------------------|-------------------|
| 地區             | `area_name`       |
| 號次             | `cand_no`         |
| 姓名             | `cand_name`       |
| 性別             | `cand_sex`        |
| 出生年           | `cand_birthyear`  |
| 政黨             | `party_name`      |
| 得票數           | `ticket_num`      |
| 得票率           | `ticket_percent`  |
| 當選             | `is_victor`       |

## Scraper Flow

```
1. Fetch ELC_L0.json
2. Extract sessions 3–11, legisId in {L1, L2, L3}
3. For each session:
   a. L1 — fetch city list JSON → for each city, fetch tickets JSON → write XLSX
   b. L2 — fetch national tickets JSON → write XLSX
   c. L3 — fetch national tickets JSON → write XLSX
4. Skip files that already exist
```

## CLI

```bash
uv run python src/fetch_legislator.py              # all sessions 3–11
uv run python src/fetch_legislator.py --session 11 # single session
```

## Dependencies

Add `httpx` to project dependencies via `uv add httpx`.

## Error Handling

- Per-file failures print a warning and continue — one bad city does not abort the full run.
- A small delay between requests avoids rate limiting.
