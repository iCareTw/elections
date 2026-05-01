-- 將 touch_elections_updated_at 改為通用名稱，供多張表共用
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_elections_updated_at
BEFORE UPDATE ON elections
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

DROP FUNCTION IF EXISTS touch_elections_updated_at;

-- review_decisions 有 updated_at 欄位但原本缺少觸發器
CREATE OR REPLACE TRIGGER trg_review_decisions_updated_at
BEFORE UPDATE ON review_decisions
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

-- resolutions.mode 的合法值改為 DB 層約束
ALTER TABLE resolutions
    ADD CONSTRAINT chk_resolutions_mode CHECK (mode IN ('auto', 'new', 'manual'));

-- resolutions 原本缺少 election_id index（與 review_decisions 不一致）
CREATE INDEX IF NOT EXISTS idx_resolutions_election_id
    ON resolutions (election_id);

-- UNIQUE (candidate_id, year, type, region) leading column 已覆蓋此查詢
DROP INDEX IF EXISTS idx_candidate_elections_candidate_id;
