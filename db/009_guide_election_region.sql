-- 009_guide_election_region.sql — 公報選舉加上地區。
-- 縣市長是「同年多場、以地區區分」,校對台左樹要在年份底下列出各縣市,
-- 標題也要寫出是哪一個縣市;總統場次無地區,留 NULL。
BEGIN;

ALTER TABLE guide_elections ADD COLUMN IF NOT EXISTS region VARCHAR(16);

COMMIT;
