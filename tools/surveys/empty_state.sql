-- Start-of-check guard (tools/surveys/infrastructure.sh): no survey rows
-- beyond the two migration singletons. A leak from an earlier check on a
-- shared fixture fails here before the check writes anything.
DO $$
DECLARE
  name text;
  rows bigint;
BEGIN
  FOR name IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename LIKE 'survey%'
  LOOP
    EXECUTE format('SELECT count(*) FROM %I', name) INTO rows;
    IF name IN ('survey_settings', 'survey_recovery_identity') THEN
      IF rows <> 1 THEN
        RAISE EXCEPTION 'Survey state leaked: % has % rows, expected 1', name, rows;
      END IF;
    ELSIF rows <> 0 THEN
      RAISE EXCEPTION 'Survey state leaked: % has % rows', name, rows;
    END IF;
  END LOOP;
END $$;
