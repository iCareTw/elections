.PHONY: install
install:
	uv sync
	uv run playwright install chromium

.PHONY: test
test:
	uv run pytest tests/unit tests/integration -v

.PHONY: test-unit
test-unit:
	uv run pytest tests/unit -v

.PHONY: test-integration
test-integration:
	uv run pytest tests/integration -v

.PHONY: cov
cov:
	 open htmlcov/index.html

## 啟動整合網頁(身分判定 + 公報校對台,同一 app;頂部分頁切換)
## 覆寫: WEB_PORT、WEB_SCHEMA(如 guide_demo 做隔離測試,預設用 .env)
WEB_PORT   ?= 23088
WEB_SCHEMA ?=
.PHONY: web
web:
	$(if $(WEB_SCHEMA),POSTGRES_SCHEMA=$(WEB_SCHEMA) ,)uv run uvicorn "src.webapp.app:create_app" --factory --host 127.0.0.1 --port $(WEB_PORT)

.PHONY: ui
ui:
	uv run python -m src.webapp.app

## WARNING: 爬取所有選舉公報! 會佔用非常大的 Disk 空間 (約 100GB)，請斟酌使用!
.PHONY: crawl-voter-guide
crawl-voter-guide:
	uv run python -m src.fetch_voter_guide

.PHONY: crawl-data
crawl-data: crawl-township crawl-village crawl-indigenous

.PHONY: crawl-township
crawl-township:
	uv run src/fetch_township.py

.PHONY: crawl-village
crawl-village:
	uv run src/fetch_village.py

.PHONY: crawl-indigenous
crawl-indigenous:
	uv run src/fetch_indigenous.py

# # ---------------------- 國家元首 ----------------------
# 	uv run python main.py --type president --year 1996
# 	uv run python main.py --type president --year 2000
# 	uv run python main.py --type president --year 2004
# 	uv run python main.py --type president --year 2008
# 	uv run python main.py --type president --year 2012
# 	uv run python main.py --type president --year 2016
# 	uv run python main.py --type president --year 2020
# 	uv run python main.py --type president --year 2024

# # ---------------------- 縣市首長 ----------------------
# 	uv run python main.py --type mayor --year 1994   # 83年直轄市長選舉
# 	uv run python main.py --type mayor --year 1997   # 86年縣市長選舉
# 	uv run python main.py --type mayor --year 1998   # 87年直轄市長選舉
# 	uv run python main.py --type mayor --year 2001   # 90年縣市長選舉
# 	uv run python main.py --type mayor --year 2002   # 91年直轄市長選舉
# 	uv run python main.py --type mayor --year 2005   # 94年縣市長選舉
# 	uv run python main.py --type mayor --year 2006   # 95年直轄市長選舉
# 	uv run python main.py --type mayor --year 2009   # 98年縣市長選舉
# 	uv run python main.py --type mayor --year 2010   # 99年直轄市長選舉
# 	uv run python main.py --type mayor --year 2014   # 103年直轄市長 + 縣市長（2 檔合併）
# 	uv run python main.py --type mayor --year 2018   # 107年直轄市長 + 縣市長（2 檔合併）
# 	uv run python main.py --type mayor --year 2020   # 109年直轄市長_補選（高雄）
# 	uv run python main.py --type mayor --year 2022   # 111年直轄市長 + 縣市長 + 縣市長_重選（3 檔合併）

# # ---------------------- 立法委員(區域) ----------------------
# 	uv run python main.py --type legislator --session 3
# 	uv run python main.py --type legislator --session 4
# 	uv run python main.py --type legislator --session 5
# 	uv run python main.py --type legislator --session 6
# 	uv run python main.py --type legislator --session 7
# 	uv run python main.py --type legislator --session 8
# 	uv run python main.py --type legislator --session 9
# 	uv run python main.py --type legislator --session 10
# 	uv run python main.py --type legislator --session 11

# # ---------------------- 立法委員(不分區) ----------------------
# 	uv run python main.py --type party-list --session 7
# 	uv run python main.py --type party-list --session 8
# 	uv run python main.py --type party-list --session 9
# 	uv run python main.py --type party-list --session 10
# 	uv run python main.py --type party-list --session 11

.PHONY: voter_guide
voter_guide:
	uv run python -m src.fetch_voter_guide --type president,legislator,mayor,councilor,mna

# ==================== 公報校對台 (guide) ====================
# 解析公報 PDF → 匯入 DB → 網頁校對(標記 / AI 修復 / 手動 / 圈選補照片 / 版本)
# 可覆寫變數: GUIDE_PDF、GUIDE_YAML、GUIDE_PORT、GUIDE_SCHEMA(隔離測試用,如 guide_demo)、FORCE=1
GUIDE_PDF    ?= _data/voter_guide/president/113年第16任總統副總統.pdf
GUIDE_YAML   ?= _out/parsed/113.yaml
GUIDE_PORT   ?= 23099
GUIDE_SCHEMA ?=
guide_env = $(if $(GUIDE_SCHEMA),POSTGRES_SCHEMA=$(GUIDE_SCHEMA) ,)

## 解析一份公報 PDF,產出 YAML + 切圖 + 照片到 _out/parsed
.PHONY: guide-parse
guide-parse:
	uv run python -m src.voter_guide.pipeline "$(GUIDE_PDF)" --out-dir _out/parsed

## 匯入解析結果到 DB(重複載入需加 FORCE=1 強制重灌)
.PHONY: guide-load
guide-load:
	$(guide_env)uv run python -m src.voter_guide.guide_load "$(GUIDE_YAML)" "$(GUIDE_PDF)" _out/parsed $(if $(FORCE),--force,)

## 啟動校對台網頁,瀏覽器開 http://127.0.0.1:$(GUIDE_PORT)/guide
.PHONY: guide-web
guide-web:
	$(guide_env)uv run uvicorn "src.webapp.app:create_app" --factory --host 127.0.0.1 --port $(GUIDE_PORT)
