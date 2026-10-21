-- Local Compose only. Replace this password through your secret manager in RDS.
CREATE ROLE paper_readonly LOGIN PASSWORD 'paper_readonly_local' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE paper_trader TO paper_readonly;
GRANT USAGE ON SCHEMA public TO paper_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO paper_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE paper IN SCHEMA public GRANT SELECT ON TABLES TO paper_readonly;
