-- 011_guide_election_parse_log.sql — 這場公報是怎麼讀出來的。
-- 一份公報會依序試多種讀法(文字層 → 匡線+OCR → 影像找格線 …),
-- 把「試了什麼、讀到幾人、跟名冊對上幾個、為什麼被否決」整份存下來,
-- 校對台看得到,解析不出來時也知道卡在哪。
BEGIN;

ALTER TABLE guide_elections ADD COLUMN IF NOT EXISTS parse_log TEXT;

COMMIT;
