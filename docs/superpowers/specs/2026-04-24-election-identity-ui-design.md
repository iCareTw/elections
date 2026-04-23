# Election Identity UI 設計文件

**日期：** 2026-04-24  
**範圍：** `v1` 本地 Web App，用於跨 `election` 的同名人物身分判斷

---

## 目標

提供一個比目前 CLI 更容易判讀的本地 UI，協助使用者確認：

- 不同 `election` 的同名候選人，是否為同一人
- 每筆來源候選人最後被編入哪個 `id`

`v1` 聚焦在「人物比對與編碼」，不做通用資料編輯器。

---

## 名詞

- `election`
  一個輸入來源單位，例如：
  - `_data/president/第16任總統副總統選舉.xlsx`
  - `11th.yaml`

- `incoming record`
  目前正在處理的某一筆來源候選人資料。

- `existing candidate`
  已經存在於整合結果中的人物資料。

---

## 判斷規則

### 自動判斷

- 同名 + 同生日 + 唯一匹配
  - 直接視為同一人
  - 自動編入同一個 `id`

### 需要人工判斷

- 同名 + 不同生日
- 同名 + 缺生日
- 同名 + 同生日，但對到不只一筆既有資料

### 建立新人物

- 找不到同名人物
- 使用者判定「都不是同一人」

---

## UI

### 左側 Navigator

- 緊湊樹狀清單
- 以 `type > election` 呈現
- `type` 可收合
- 每個 `election` 顯示最少必要資訊：
  - 名稱或年份 / 屆次
  - 狀態：`todo / in_progress / done`

### 右側 Workspace

右側一次只處理一個 `incoming record`，畫面只做這件事：

- 顯示目前這筆 `incoming record`
- 顯示疑似相同人的 `existing candidate`（可複數）
- 讓使用者快速決定：
  - 編入既有 `id`
  - 建立新 `id`
  - 跳過

`v1` 不做複雜 diff 畫面，也不做通用 YAML 編輯功能。

---

## 記錄資料

每次判斷都需要記錄：

- `election`
- 來源中的第幾筆候選人
- 候選人姓名
- 候選人生日
- 最後編到哪個 `id`
- `auto` 或 `manual`
- 操作時間

---

## 輸出

- 最終輸出仍為 `candidates.yaml`
- App 需保留判斷紀錄，讓之後能追查：
  - 哪個 `election`
  - 哪一筆候選人
  - 被編入哪個 `id`

---

## `v1` 明確不做

- 通用的 `candidates.yaml` 編輯器
- 即時監看 `_data/` 變化
- 多人協作
- 複雜 merge 視覺化
- 超出「同名人物身分判斷」的資料治理功能
