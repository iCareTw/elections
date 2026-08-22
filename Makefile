# 只收錄可安全重複執行的常用指令。
# 會刪除、覆寫或重建 DB／既有成果的操作不得放進 Makefile，避免誤觸；
# 這類維護操作應直接使用原始 CLI，並先確認其影響範圍。

.PHONY: install
install:
	uv sync
	uv run playwright install chromium


.PHONY: web
web:
	uv run uvicorn "src.webapp.app:create_app" --factory --host 127.0.0.1 --port 23088

# WARNING: 下載主要選舉類型的公報 PDF 到 _data/；可能耗時並占用大量磁碟空間。
.PHONY: voter_guide
voter_guide:
	uv run python -m src.fetch_voter_guide --type president,legislator,mayor,councilor,mna
