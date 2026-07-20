# 選舉公報解析 (voter guide)

從中選會選舉公報 PDF 擷取候選人資料（號次、姓名、生日、性別、政黨、學歷、經歷、相片）。

## 用法

```bash
# 解析 PDF → 每屆一份 YAML（含每欄信心標記）與相片
uv run python -m src.voter_guide.pipeline <pdf...> --out-dir <dir>

# 匯入 DB 後於網頁檢視/校對(公報校對台):make web → /guide
```

## 運作方式

- **切分**：以表格框線把每位參選人、每個欄位切成單格取文字（`geometry`）。
- **驗證**：把單格截圖交給本機視覺模型「盲讀」當獨立第二來源（`vision`），
  程式比對兩路一致度，標成五級信心：完全一致／幾乎一致／大部分一致／資料不可靠／無法解析（`verify`）。
- 掃描圖無內嵌文字時，改用 macOS 內建 Vision OCR 取字。

## 模組

`src/voter_guide/`：`geometry`（切分）、`vision`（盲讀）、`verify`（信心）、`pipeline`（串接）、`guide_load`（匯入 DB）、`guide_repair`（AI 修復）、`guide_crop`（照片裁切）。網頁檢視/校對在 `src/webapp/routes/guide.py` 與 `templates/guide/`。
