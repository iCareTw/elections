"""把解析結果 YAML + 相片 產成一個自包含 HTML 檢視頁(相片內嵌 base64)。

用法:
    uv run python -m src.voter_guide.report <out-dir> [-o report.html]
"""
from __future__ import annotations

import argparse
import base64
import html
from pathlib import Path

import yaml

GRADE_COLOR = {
    "完全一致": "#2e7d32",
    "幾乎一致": "#7cb342",
    "大部分一致": "#f9a825",
    "資料不可靠": "#ef6c00",
    "無法解析": "#c62828",
    "看圖存疑": "#9e9e9e",
}
SHOW_FIELDS = ["出生年月日", "性別", "學歷", "經歷"]


def _img(path: str | None) -> str:
    if not path or not Path(path).exists():
        return '<div class="noimg">無相片</div>'
    b = base64.b64encode(Path(path).read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b}">'


def _badge(grade: str) -> str:
    if not grade or grade == "不適用":
        return ""
    c = GRADE_COLOR.get(grade, "#666")
    return f'<span class="badge" style="background:{c}">{grade}</span>'


def _person(rec: dict, verify: dict, role: str) -> str:
    if not rec:
        return ""
    rows = [f'<div class="nm">{html.escape(rec.get("姓名") or "?")} '
            f'<small>{role}</small> {_badge(verify.get("姓名",{}).get("grade",""))}</div>']
    rows.append(_img(rec.get("相片")))
    for f in SHOW_FIELDS:
        val = rec.get(f)
        if val is None:
            continue
        g = verify.get(f, {}).get("grade", "")
        cls = "long" if f in ("學歷", "經歷") else "short"
        rows.append(f'<div class="fld {cls}"><b>{f}</b> {_badge(g)}'
                    f'<div class="val">{html.escape(str(val))}</div></div>')
    return f'<div class="person">{"".join(rows)}</div>'


def _group(g: dict) -> str:
    v = g.get("_verify", {})
    head = (f'<div class="ghead">#{g.get("號次")} '
            f'<span class="party">{html.escape(g.get("政黨") or "")}</span></div>')
    body = _person(g.get("總統"), v.get("總統", {}), "總統") + \
        _person(g.get("副總統"), v.get("副總統", {}), "副總統")
    return f'<div class="group">{head}<div class="pair">{body}</div></div>'


def build(out_dir: Path, out_file: Path):
    yamls = sorted(p for p in out_dir.glob("*.yaml"))
    sections = []
    for y in yamls:
        data = yaml.safe_load(y.read_text(encoding="utf-8")) or []
        if not data:
            continue
        groups = "".join(_group(g) for g in data)
        sections.append(f'<h2>{y.stem} 年</h2><div class="groups">{groups}</div>')

    css = """
    body{font-family:-apple-system,"PingFang TC",sans-serif;margin:24px;background:#fafafa;color:#222}
    h2{border-bottom:2px solid #ccc;padding-bottom:4px;margin-top:40px}
    .groups{display:flex;flex-wrap:wrap;gap:16px}
    .group{border:1px solid #ddd;border-radius:8px;background:#fff;padding:12px;width:520px}
    .ghead{font-size:18px;font-weight:700;margin-bottom:8px}
    .party{color:#1565c0;font-weight:600}
    .pair{display:flex;gap:12px}
    .person{flex:1;min-width:0}
    .person img{width:96px;height:auto;border:1px solid #ccc;border-radius:4px;display:block;margin:4px 0}
    .noimg{width:96px;height:120px;background:#eee;color:#999;display:flex;align-items:center;justify-content:center;font-size:12px}
    .nm{font-size:16px;font-weight:700}
    .nm small{color:#888;font-weight:400}
    .fld{margin:6px 0}
    .fld b{font-size:12px;color:#555}
    .val{font-size:13px;line-height:1.5;white-space:pre-wrap}
    .long .val{color:#333}
    .badge{color:#fff;font-size:10px;padding:1px 6px;border-radius:10px;margin-left:4px;vertical-align:middle}
    """
    legend = ('<div class="legend">' +
              " ".join(_badge(g) for g in GRADE_COLOR) + "</div>")
    doc = (f"<!doctype html><meta charset=utf-8><title>總統公報解析檢視</title>"
           f"<style>{css}</style><h1>總統公報解析結果</h1>{legend}"
           f"{''.join(sections)}")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(doc, encoding="utf-8")
    return out_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_file = Path(args.output) if args.output else out_dir / "report.html"
    print("wrote", build(out_dir, out_file))


if __name__ == "__main__":
    main()
