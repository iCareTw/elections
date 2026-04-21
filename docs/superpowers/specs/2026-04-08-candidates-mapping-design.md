# 候選人 Mapping 設計文件

**日期：** 2026-04-08  
**範圍：** 2012 年以後，四大選舉類型（國家元首、縣市首長、立法委員、縣市議員）

---

## 目標

從 `_data/` 的原始選舉資料（中選會公告），產生並維護一份 `candidates.yaml`，記錄候選人的參選紀錄與黨籍歸屬。

---

## 檔案結構

```
elections/
├── _data/                  # 原始資料（.gitignore）
│   ├── president/          # 總統副總統選舉 xlsx
│   ├── mayor/              # 縣市首長選舉 xlsx
│   ├── legislator/         # 立法委員選舉（暫不處理）
│   └── council/            # 縣市議員選舉（暫不處理）
├── candidates.yaml         # 主 mapping 檔
└── election_types.yaml     # type enum 參考表
```

---

## `candidates.yaml` Schema

```yaml
- name: string        # 完整原始姓名（含英文、原住民族名）
  id: string          # 唯一識別碼（見 ID 規則）
  birthday: integer|null  # yyyy（僅年份整數）或 null
  elections:
    - year: integer        # 西元年份
      type: string         # 必須是 election_types.yaml 中的合法值
      region: string       # 縣市全名（官方用字）；國家元首填 全國；立委填選舉區名稱；縣市議員填縣市名稱（不含選區）
      party: string        # 推薦政黨（原始文字）
      elected: integer     # 1 = 當選，0 = 落選，null = 不分區遞補（視政黨票數）
      session: integer     # （選填）立法院屆次，僅立委使用
      order_id: integer    # （選填）不分區名單排序，非直選，依政黨票數遞補
      ticket: integer      # （選填）選舉公報號次
  # elections 依 year 升冪排序（越早的選舉越前面）
```

### 實際範例

```yaml
- name: 柯文哲
  id: id_柯文哲_1959
  birthday: 1959
  elections:
    - year: 2014
      type: 縣市首長
      region: 臺北市
      party: 無黨籍
      elected: 1
    - year: 2018
      type: 縣市首長
      region: 臺北市
      party: 無黨籍
      elected: 1
    - year: 2024
      type: 國家元首_總統
      region: 全國
      party: 台灣民眾黨
      elected: 0
      ticket: 1

- name: 賴清德
  id: id_賴清德_1959
  birthday: 1959
  elections:
    - year: 2024
      type: 國家元首_總統
      region: 全國
      party: 民主進步黨
      elected: 1
      ticket: 2

- name: 蔣萬安
  id: id_蔣萬安_1978
  birthday: 1978
  elections:
    - year: 2022
      type: 縣市首長
      region: 臺北市
      party: 中國國民黨
      elected: 1

- name: 伍麗華Saidhai．Tahovecahe
  id: id_伍麗華Saidhai．Tahovecahe_1969
  birthday: 1969
  elections:
    - year: 2020
      type: 立法委員
      region: 山地原住民 全國
      party: 民主進步黨
      elected: 1
      session: 10

- name: 許淑華
  id: id_許淑華_1973
  birthday: 1973
  elections:
    - year: 2016
      type: 縣市議員
      region: 臺北市
      party: 民主進步黨
      elected: 1

- name: 許淑華
  id: id_許淑華_1975
  birthday: 1975
  elections:
    - year: 2014
      type: 縣市首長
      region: 南投縣
      party: 中國國民黨
      elected: 0
```

---

## ID 規則

### 基本格式

```
id_<正規化姓名>
```

### 正規化規則（寫死於程式）

| 移除對象 | 保留 |
|---------|------|
| 空白（全形/半形） | 中文字 |
| 特殊符號 ‧ · • ( ) （ ） 【 】 | 英文字母 |
| 罕見字（hardcoded list） | 數字 |

範例：`伍麗華Saidhai‧Tahovecahe` → `id_伍麗華SaidhaiTahovecahe`

### 同名衝突解法

| 情況 | ID 格式 |
|------|---------|
| 有 birthday | `id_許淑華_1973` |
| 無 birthday | `id_許淑華` |
| 同名同年（罕見） | 人工處理 |

---

## 生日格式（birthday）

birthday 一律填整數年份 `yyyy`；無資料時填 `null`。

---

## `election_types.yaml` Schema

type enum 清單，每個 type 帶 `aliases` 陣列，記錄對應的原始文字寫法。

```yaml
- id: 國家元首_總統
  aliases:
    - 總統副總統選舉

- id: 國家元首_副總統
  aliases:
    - 總統副總統選舉

- id: 縣市首長
  aliases:
    - 103年直轄市市長選舉
    - 103年縣(市)長選舉
    - 107年直轄市市長選舉
    - 107年縣(市)長選舉
    - 111年直轄市市長選舉
    - 111年縣(市)長選舉

- id: 立法委員
  aliases:
    - 第X屆XX縣市立法委員選舉
    - 第X屆XX縣市立法委員補選

- id: 縣市議員
  aliases:
    - 103年直轄市議員選舉
    - 103年縣(市)議員選舉
    - 107年直轄市議員選舉
    - 107年縣(市)議員選舉
    - 111年直轄市議員選舉
    - 111年縣(市)議員選舉
```

### region 標準值

使用官方全名，`臺` 不寫作 `台`：

```
臺北市、新北市、桃園市、臺中市、臺南市、高雄市、
基隆市、新竹市、新竹縣、嘉義市、嘉義縣、
宜蘭縣、苗栗縣、彰化縣、南投縣、雲林縣、
屏東縣、花蓮縣、臺東縣、澎湖縣、金門縣、連江縣
```

國家元首：`region: 全國`

---

## 工作流程

CLI 每次處理一種選舉類型、一個年度：

```
uv run python main.py --type mayor --year 2022
uv run python main.py --type president --year 2024
```

### 首次執行（candidates.yaml 不存在）

直接從 raw data 產生並寫入 `candidates.yaml`。

### 後續執行（candidates.yaml 已存在）

解析新資料後與現有 yaml 比對，分三種情況：

| 情況 | 處理方式 |
|------|---------|
| **NEW** — 現有 yaml 找不到此人 | 自動新增 |
| **EXISTS** — 找到同一人，新增一筆 election | 自動合併 |
| **CONFLICT** — 同名，但 birthday 年份或 party 不符 | 暫停，請使用者人工判斷 |

自動處理的筆數會列出摘要；CONFLICT 才會逐一詢問使用者選擇：
- 合併至現有某人
- 新增為第三人
- 跳過（留待下次處理）

確認完畢後寫入 `candidates.yaml`。

---

## 現階段範圍

- **已納入：** president、mayor（資料結構一致，優先處理）
- **暫緩：** legislator、council（原始資料格式不一致，待整理後再行擴充）
- **不含：** 鄉鎮區長、里長、鄉鎮市民代表（超出現階段範圍）
