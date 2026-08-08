-- Runs once on first Postgres container init (docker-entrypoint-initdb.d).
-- Bootstrap user (postgres) stays superuser for admin/extensions.
-- App + tests connect as legaluser, which must NOT be a superuser so RLS applies.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE ROLE legaluser LOGIN PASSWORD 'legalpass'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE legaldb TO legaluser;
GRANT ALL ON SCHEMA public TO legaluser;
GRANT CREATE ON SCHEMA public TO legaluser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO legaluser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO legaluser;

-- Test database (used by pytest / CI)
CREATE DATABASE legaldb_test OWNER postgres;
GRANT CONNECT ON DATABASE legaldb_test TO legaluser;
\connect legaldb_test
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO legaluser;
GRANT CREATE ON SCHEMA public TO legaluser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO legaluser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO legaluser;
