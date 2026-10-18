SET statement_timeout = '15min';
\timing on
SELECT count(*) FROM extractor.lt_tb WHERE "Body" ~* '\merror\M';
