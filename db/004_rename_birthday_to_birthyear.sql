BEGIN;

-- 將 birthday 欄位/payload key 更名為 birthyear (真實語意為出生年份), 並補 NOT NULL.
-- 冪等寫法: 可在已套用過的 schema 上重複執行 (init_schema 會重複呼叫).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'source_records' AND column_name = 'birthday'
    ) THEN
        ALTER TABLE source_records RENAME COLUMN birthday TO birthyear;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'candidates' AND column_name = 'birthday'
    ) THEN
        ALTER TABLE candidates RENAME COLUMN birthday TO birthyear;
    END IF;
END $$;

ALTER TABLE source_records ALTER COLUMN birthyear SET NOT NULL;
ALTER TABLE candidates ALTER COLUMN birthyear SET NOT NULL;

-- payload JSON key: birthday -> birthyear (僅處理仍含舊 key 的列)
UPDATE source_records
SET payload = (payload - 'birthday') || jsonb_build_object('birthyear', payload -> 'birthday')
WHERE payload ? 'birthday';

COMMIT;
