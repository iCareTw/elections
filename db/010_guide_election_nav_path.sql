-- 010_guide_election_nav_path.sql — 公報選舉在校對台左樹的位置。
-- 立委的層級比總統/縣市長深(屆次 → 區域/不分區/原住民/補選 → 縣市 → 選舉區),
-- 左樹改成照這個路徑攤開,不再由 type/year/region 三個欄位硬拼。
-- 路徑以「/」分段,最後一段是這場選舉自己的標題。
BEGIN;

ALTER TABLE guide_elections ADD COLUMN IF NOT EXISTS nav_path TEXT;

-- 既有的總統/縣市長場次補上路徑,沿用原本左樹的長相
UPDATE guide_elections
   SET nav_path = '總統/第' || session || '任 ' || year
 WHERE nav_path IS NULL AND type = 'president' AND session IS NOT NULL;

UPDATE guide_elections
   SET nav_path = '縣市長/' || year || '/'
                  || replace(replace(id, 'mayor_' || year || '_', ''), '_', ' ')
 WHERE nav_path IS NULL AND type = 'mayor';

COMMIT;
