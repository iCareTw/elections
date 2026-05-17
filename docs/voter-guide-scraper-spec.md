# 選舉公報爬蟲規格

## 目標

從中選會兩個網站爬取所有選舉公報 PDF，儲存到本地 `_data/voter_guide/` 目錄。

- 主站：`https://bulletin.cec.gov.tw/` （動態頁面，需等待渲染）
- 村里長網站：`https://eebulletin.cec.gov.tw/` （動態頁面，需等待渲染）

## 注意事項

- 兩個網站均為動態頁面，不可用 curl/直接 HTTP 請求，必須用 Playwright 等待 DOM 渲染後再擷取連結
- PDF 下載可直接用 HTTP GET（非動態）
- 斷點續傳：已存在的 PDF 檔案跳過不重新下載
- 本地根目錄：`_data/voter_guide/`

---

## 各類別路徑規格

### 01總統副總統 → `president/`

結構：直接是 PDF，無子目錄。

```
president/{filename}.pdf
```

爬取入口：`https://bulletin.cec.gov.tw/?dir=01選舉公報/01總統副總統`

---

### 02立法委員 → `legislator/`

結構：三到四層。

```
legislator/{Nth_YYY}/{sub_type}/{filename}.pdf          # party / native / by-election
legislator/{Nth_YYY}/district/{county}/{filename}.pdf  # district 下有縣市層
```

**Layer 2 命名規則**：原始名稱如 `105年第9屆` → `09th_105`，`113年第11屆` → `11th_113`

**Layer 3 命名對照**：

| 網站原始名稱 | 本地目錄名稱 |
|---|---|
| 01區域 | `district` |
| 02全國不分區及僑居國外國民 | `party` |
| 03平地山地原住民 | `native` |
| 04補選 | `by-election` |

- `district` 底下保留縣市子目錄（原始名稱，如 `01臺北市`），再放 PDF
- 其他三種（party / native / by-election）底下直接放 PDF

爬取入口：`https://bulletin.cec.gov.tw/?dir=01選舉公報/02立法委員`

---

### 03直轄市長 + 04縣市長 → `mayor/`

結構：年份下直接放 PDF（所有縣市 flatten 到同一層）。

```
mayor/{YYY}/{filename}.pdf
```

**特例（04縣市長 111年）**：網站有 `01紙本公報` / `02有聲公報` 中間層，只爬 `01紙本公報` 底下的 PDF，本地不建這一層目錄，直接 flatten 到 `mayor/111/`。

**04縣市長 其他年份**：網站有縣市子目錄層（如 `07新竹縣`），flatten 掉，PDF 直接放 `mayor/{YYY}/`。

爬取入口：
- `https://bulletin.cec.gov.tw/?dir=01選舉公報/03直轄市長`
- `https://bulletin.cec.gov.tw/?dir=01選舉公報/04縣市長`

---

### 05直轄市議員 + 06縣市議員 → `councilor/`

結構：年份 → 縣市 → PDF。

```
councilor/{YYY}/{county}/{filename}.pdf
```

縣市目錄名稱依原始網站命名（如 `04臺中市`）。

爬取入口：
- `https://bulletin.cec.gov.tw/?dir=01選舉公報/05直轄市議員`
- `https://bulletin.cec.gov.tw/?dir=01選舉公報/06縣市議員`

---

### 07省長 → `province/`

結構：頂層直接是 PDF，無年份子目錄。

```
province/{filename}.pdf
```

爬取入口：`https://bulletin.cec.gov.tw/?dir=01選舉公報/07省長`

---

### 08省議員 → `province_councilor/`

結構：083年 → 直接是 PDF。

```
province_councilor/083/{filename}.pdf
```

爬取入口：`https://bulletin.cec.gov.tw/?dir=01選舉公報/08省議員`

---

### 09國大代表 → `mna/`

結構：依年份不同有差異。

```
# 080年、085年：有區域/不分區分層，區域下有縣市層
mna/{YYY}/01區域/{county}/{filename}.pdf
mna/{YYY}/02全國不分區及僑居國外國民/{filename}.pdf

# 094年特例：頂層直接一個 PDF，無任何子目錄
mna/094/{filename}.pdf
```

Layer 3（分類目錄）使用**原始中文名稱**（不轉英文）。

爬取入口：`https://bulletin.cec.gov.tw/?dir=01選舉公報/09國大代表`

---

### 103年以後鄉鎮市長、代表及村里長 → 多個子類別

爬取入口：`https://eebulletin.cec.gov.tw/`

頂層為年份目錄（103 / 107 / 111 / 以後新增的年份）。  
每個年份下為縣市目錄，縣市下又分選舉類別。  
只爬以下三種類別，其餘（市長、市議員、有聲公報等）全部忽略：

#### 05村里長 → `village/`

```
village/{YYY}/{county}/{district}/{filename}.pdf
```

- `{county}`：縣市目錄原始名稱，如 `05臺中市`
- `{district}`：鄉鎮市區目錄原始名稱，如 `臺中市南屯區`

範例：
```
village/111/05臺中市/臺中市南屯區/臺中市南屯區向心里.pdf
village/107/10彰化縣/員林市/員林市三條里里長.pdf
```

#### 03原住民區長 → `indigenous_chief/`

```
indigenous_chief/{YYY}/{county}/{filename}.pdf
```

- `{county}`：縣市目錄原始名稱，如 `05臺中市`
- 並非所有縣市都有此類別

#### 04原住民區民代表 → `indigenous_rep/`

```
indigenous_rep/{YYY}/{county}/{filename}.pdf
```

- `{county}`：縣市目錄原始名稱，如 `05臺中市`
- 並非所有縣市都有此類別

---

## 目錄結構總覽

```
_data/voter_guide/
├── president/
├── legislator/
│   └── 09th_105/
│       ├── district/
│       │   └── 01臺北市/
│       ├── party/
│       ├── native/
│       └── by-election/
├── mayor/
├── councilor/
│   └── 111/
│       └── 04臺中市/
├── province/
├── province_councilor/
│   └── 083/
├── mna/
│   ├── 080/
│   │   ├── 01區域/
│   │   │   └── 01臺北市/
│   │   └── 02全國不分區及僑居國外國民/
│   └── 094/
├── village/
│   └── 111/
│       └── 05臺中市/
│           └── 臺中市南屯區/
├── indigenous_chief/
│   └── 111/
│       └── 05臺中市/
└── indigenous_rep/
    └── 111/
        └── 05臺中市/
```
