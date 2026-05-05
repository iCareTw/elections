# Candidate Name Special Cases

此文件記錄不適合寫成通則的候選人姓名特殊處理.

## 一次性 DB 修正

本次只修改 identity-ui DB, 不修改 `_data/` 原始檔.

| 原 DB 姓名 | 修正後姓名 | 修正後 Candidate ID | 處理理由 |
| --- | --- | --- | --- |
| 傅崑萁 | 傅崐萁 | `id_傅崐萁_1962` | 疑似早期資料錯字, 合併到既有傅崐萁身分 |
| 尹伶瑛 | 尹令瑛 | `id_尹令瑛_1957` | 使用原名作為 canonical name |
| 葉毓蘭 | 游毓蘭 | `id_游毓蘭_1958` | 葉毓蘭為舊名, 本專案從頭到尾以游毓蘭記錄 |
| 章孝嚴 | 蔣孝嚴 | `id_蔣孝嚴_1941` | 本專案統一使用蔣孝嚴作 canonical name |
| 簡東明 | 簡東明Uliw.Qaljupayare | `id_簡東明_1951` | 同一人在不同選舉資料揭露姓名不同, 保留短 ID, 姓名統一為含族名版本 |

修改範圍:

- `candidates`: 舊 ID 刪除或改名, canonical name 統一為修正後姓名.
- `candidate_elections`: 舊 ID 的參選紀錄移到修正後 ID.
- `resolutions`: 已 commit 的 candidate reference 移到修正後 ID.
- `review_decisions`: 若仍有草稿決策, candidate reference 移到修正後 ID.
- `source_records`: `name` 與 `payload.name` 同步改為修正後姓名.

驗證方式:

- 舊姓名與舊 Candidate ID 在 `candidates`, `candidate_elections`, `resolutions`, `review_decisions`, `source_records`, `source_records.payload.name` 中應為 0 筆.
- 修正後筆數: 傅崐萁 8 筆參選紀錄與 8 筆 resolution, 尹令瑛 4 筆參選紀錄與 4 筆 resolution, 游毓蘭 2 筆參選紀錄與 2 筆 resolution, 蔣孝嚴 3 筆參選紀錄與 3 筆 resolution, 簡東明Uliw.Qaljupayare 6 筆參選紀錄與 6 筆 resolution.
