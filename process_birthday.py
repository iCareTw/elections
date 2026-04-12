#!/usr/bin/env python3
"""
將 YAML 檔案中的民國生日轉換為西元生日。

用法: uv run process_birthday.py <input.yaml>
輸出: <input>-new.yaml (同目錄)
"""

import sys
from pathlib import Path

import yaml


def roc_to_ce_birthday(birthday: str) -> str:
    """將民國生日 (YY/MM/DD) 轉換為西元生日 (YYYY/MM/DD)。"""
    parts = birthday.strip().split("/")
    if len(parts) != 3:
        raise ValueError(f"無法解析生日格式：{birthday!r}，期望格式為 YY/MM/DD")

    roc_year, month, day = parts
    ce_year = int(roc_year) + 1911

    return f"{ce_year}/{month}/{day}"


def process_file(input_path: Path) -> Path:
    output_path = input_path.with_name(input_path.stem + "-new" + input_path.suffix)

    with input_path.open(encoding="utf-8") as f:
        records = yaml.safe_load(f)

    if not isinstance(records, list):
        raise TypeError("YAML 檔案的頂層結構必須為列表 (list)")

    for record in records:
        if "birthday" in record and record["birthday"] is not None:
            original = str(record["birthday"])
            record["birthday"] = roc_to_ce_birthday(original)

    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump(
            records,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    return output_path


def main() -> None:
    if len(sys.argv) != 2:
        print(f"用法: uv run {Path(__file__).name} <input.yaml>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])

    if not input_path.exists():
        print(f"錯誤：找不到檔案 {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.suffix.lower() not in {".yaml", ".yml"}:
        print(f"警告：副檔名不是 .yaml / .yml，仍嘗試處理…", file=sys.stderr)

    try:
        output_path = process_file(input_path)
        print(f"✅ 完成！輸出檔案：{output_path}")
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
    