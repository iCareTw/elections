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
  birthday: string|null  # yyyy/mm/dd，無資料為 null
  elections:
    - year: integer   # 西元年份
      type: string    # 必須是 election_types.yaml 中的合法值
      region: string|null  # 縣市全名（官方用字）或 null
      party: string   # 推薦政黨（原始文字）
      elected: integer     # 1 = 當選，0 = 落選
  # elections 依 year 升冪排序（越早的選舉越前面）
```

### 實際範例

```yaml
- name: 柯文哲
  id: id_柯文哲
  birthday: 1959
  elections:
    - year: 2014
      type: 縣市首長
      region: 臺北市
      party: 無黨籍及未經政黨推薦
      elected: 1
    - year: 2018
      type: 縣市首長
      region: 臺北市
      party: 無黨籍及未經政黨推薦
      elected: 1
    - year: 2024
      type: 國家元首
      region: null
      party: 台灣民眾黨
      elected: 0

- name: 賴清德
  id: id_賴清德
  birthday: 1959
  elections:
    - year: 2024
      type: 國家元首
      region: null
      party: 民主進步黨
      elected: 1

- name: 蔣萬安
  id: id_蔣萬安
  birthday: 1978
  elections:
    - year: 2022
      type: 縣市首長
      region: 臺北市
      party: 中國國民黨
      elected: 1

- name: 伍麗華Saidhai‧Tahovecahe
  id: id_伍麗華SaidhaiTahovecahe
  birthday: 1966
  elections:
    - year: 2020
      type: 立法委員
      region: null
      party: 民主進步黨
      elected: 1

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
| 無衝突 | `id_許淑華` |
| 同名，不同生年 | `id_許淑華_1973` / `id_許淑華_1975` |
| 同名，同年，不同月 | `id_許淑華_197305` / `id_許淑華_197310` |
| 同名，同年月，不同日 | `id_許淑華_19730522` / `id_許淑華_19731015` |
| 同名，同生日 | 人工處理 |

---

## 生日格式（birthday）

格式為 `yyyy/mm/dd`，無資料時為 `null`。自動化程序會盡量從原始資料填入，不足之處可事後人工補齊。

---

## `election_types.yaml` Schema

type enum 清單，每個 type 帶 `aliases` 陣列，記錄對應的原始文字寫法。

```yaml
- id: 國家元首
  aliases:
    - 第XX任總統副總統選舉

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

國家元首：`region: null`

---

## 工作流程

1. 執行對應的解析 script（每種選舉各一支），從 `_data/` 的 xlsx 產出草稿
2. 人工審閱草稿，判斷是否同名同姓（查 birthday 決定 id 後綴）
3. 填入 `candidates.yaml`，確認 `type` 在 `election_types.yaml` 內
4. 若遇到新選舉類型，先在 `election_types.yaml` 新增再填主檔
5. git commit

---

## 現階段範圍

- **已納入：** president、mayor（資料結構一致，優先處理）
- **暫緩：** legislator、council（原始資料格式不一致，待整理後再行擴充）
- **不含：** 鄉鎮區長、里長、鄉鎮市民代表（超出現階段範圍）
