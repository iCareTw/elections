"""
中選會補選資料的附件路徑。

部分補選在 tickets API 上 has_data=false（第 9、10 屆立委補選、T1/T2 議員補選），
候選人資料只出現在「得票數一覽表」XLS 附件：
  {BASE}/data/attachments/BEL/{subject_id}/{theme_group}/list.json
"""
import os
import re
import tempfile

import httpx
import openpyxl
import xlrd

BASE_URL = "https://db.cec.gov.tw"


def _sheet_rows(xls_bytes: bytes) -> list[list]:
    """中選會的附件副檔名一律是 .xls，但內容有舊 BIFF 也有 xlsx，依檔頭挑讀取器。"""
    if xls_bytes[:4] == b"PK\x03\x04":
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(xls_bytes)
            tmp = f.name
        try:
            ws = openpyxl.load_workbook(tmp, data_only=True).worksheets[0]
            return [["" if v is None else v for v in row] for row in ws.iter_rows(values_only=True)]
        finally:
            os.unlink(tmp)

    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as f:
        f.write(xls_bytes)
        tmp = f.name
    try:
        ws = xlrd.open_workbook(tmp).sheet_by_index(0)
        return [[ws.cell_value(i, j) for j in range(ws.ncols)] for i in range(ws.nrows)]
    finally:
        os.unlink(tmp)


def _cand_no(value) -> int | None:
    """候選人號次欄位在不同年份分別長成 1、1.0、"1"、"(1)"。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 1 else None
    match = re.fullmatch(r"\(?\s*(\d+)\s*\)?", str(value).strip())
    if not match:
        return None
    no = int(match.group(1))
    return no if no >= 1 else None


def _votes(value) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip().replace(",", "")
    try:
        return int(float(text))
    except ValueError:
        return 0


def parse_votes_xls(xls_bytes: bytes, vote_date: str, theme_name: str) -> list[dict]:
    rows = _sheet_rows(xls_bytes)
    ncols = max((len(r) for r in rows), default=0)

    # Find candidate number row and 總計 row
    cand_no_row_idx = total_row_idx = None
    for i, row in enumerate(rows):
        val0 = row[0] if row else None
        val1 = row[1] if len(row) > 1 else None
        if val0 in ("", None) and _cand_no(val1) == 1:
            cand_no_row_idx = i
        if val0 == "總計":
            total_row_idx = i

    if cand_no_row_idx is None or total_row_idx is None:
        return []

    def row_vals(idx):
        row = rows[idx]
        return list(row) + [""] * (ncols - len(row))

    cand_no_vals = row_vals(cand_no_row_idx)
    name_vals    = row_vals(cand_no_row_idx + 1)
    party_vals   = row_vals(cand_no_row_idx + 2)
    total_vals   = row_vals(total_row_idx)

    candidates = []
    for j in range(1, ncols):
        no = _cand_no(cand_no_vals[j])
        if no is None:
            continue
        name  = str(name_vals[j]).replace("\n", " ").strip()
        party = str(party_vals[j]).strip() if party_vals[j] not in ("", None) else "無"
        if not name:
            continue
        candidates.append({"no": no, "name": name, "party": party, "votes": _votes(total_vals[j])})

    if not candidates:
        return []

    total_valid = sum(c["votes"] for c in candidates)
    max_votes   = max(c["votes"] for c in candidates)

    records = []
    for c in candidates:
        party = c["party"]
        if party in ("無", "") or not party:
            party = "無黨籍"
        pct = round(c["votes"] / total_valid * 100, 2) if total_valid else 0.0
        records.append({
            "vote_date":     vote_date,
            "area_name":     theme_name,
            "cand_no":       c["no"],
            "cand_name":     c["name"],
            "cand_sex":      None,
            "cand_birthyear": None,
            "party_name":    party,
            "ticket_num":    c["votes"],
            "ticket_percent": pct,
            "is_victor":     "*" if c["votes"] == max_votes else " ",
        })
    return records


async def fetch_attachment_records(client: httpx.AsyncClient, item: dict) -> list[dict]:
    """讀取一場補選的「得票數一覽表」附件，回傳候選人記錄；找不到附件時回傳空 list。"""
    list_url = (
        f"{BASE_URL}/static/elections/data/attachments/"
        f"{item['type_id']}/{item['subject_id']}/{item['theme_group']}/list.json"
    )
    r = await client.get(list_url)
    r.raise_for_status()
    attachments = r.json()

    # 同一場補選會同時附「得票數一覽表」與「各投開票所得票數一覽表」，只要前者
    entry = next(
        (
            a
            for a in attachments
            if "得票數一覽表" in a.get("file_name", "") and "投開票所" not in a.get("file_name", "")
        ),
        None,
    )
    if entry is None:
        return []

    xls = await client.get(f"{BASE_URL}/static/{entry['file_path']}")
    xls.raise_for_status()
    return parse_votes_xls(xls.content, item.get("vote_date", ""), item["theme_name"])
