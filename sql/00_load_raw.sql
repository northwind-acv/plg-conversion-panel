-- 00_load_raw.sql
-- Only needed locally in DuckDB. In Snowflake the tables already exist, skip this.

CREATE OR REPLACE TABLE sessions      AS SELECT * FROM read_csv_auto('data/sessions.csv');
CREATE OR REPLACE TABLE signups       AS SELECT * FROM read_csv_auto('data/signups.csv');
CREATE OR REPLACE TABLE opportunities AS SELECT * FROM read_csv_auto('data/opportunities.csv');
