# db/ — Migration 規範

此目錄內的 `.sql` 檔案為**不可異動**的 migration 歷史紀錄.

## 規則

- **禁止修改任何已存在的 `.sql` 檔案**
- 需要變更 schema 時, 一律新增下一號的 migration 檔案, 例如 `003_xxx.sql`
- 每個 migration 檔案必須包在 `BEGIN; ... COMMIT;` 之內

## 原因

這些檔案構成可重置、可追蹤的 schema 變更歷史. 直接修改舊檔案會破壞歷史紀錄, 導致無法重現任意版本的 DB 狀態.
