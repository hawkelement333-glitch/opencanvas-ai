# Controlled-agent PostgreSQL trigger testing

Status: runnable integration-test architecture. This does not add agent execution behavior.

Migration `20260721_0007` installs PostgreSQL triggers that reject direct `UPDATE` and `DELETE`
against all ten controlled-agent security tables. SQLite remains the portable test path;
PostgreSQL is authoritative for the PostgreSQL trigger function.

## Safety model

The test requires `OPENCANVAS_POSTGRES_TEST_URL`. It refuses:

- non-`postgresql+asyncpg` URLs;
- database names without a distinct `test`, `testing`, or `ci` segment;
- names containing development, staging, or production terminology;
- non-loopback hosts outside CI.

The configured URL is an administration database used only to create a random
`opencanvas_agent_test_<uuid>` database. Alembic upgrades that disposable database to head. The
fixture terminates its remaining connections and drops it afterward. A configured but unavailable
server fails the test; an absent URL produces an explicit `NOT RUN` skip.

## Local Docker command

The `postgres-test` Compose profile uses PostgreSQL 17 with a temporary in-memory data directory and
the local-only placeholder password `local-test-only`.

```powershell
docker compose --profile test up -d postgres-test
$env:OPENCANVAS_POSTGRES_TEST_URL = "postgresql+asyncpg://opencanvas_test:local-test-only@127.0.0.1:55432/opencanvas_test_admin"
pnpm test:postgres
docker compose --profile test down
```

Do not substitute a development, staging, production, or persistent database. Do not commit a real
credential. If Docker or PostgreSQL is unavailable, record the result as `NOT RUN`; a skipped test
is not a pass.

## Coverage

The direct-SQL integration test verifies:

- the migration reaches PostgreSQL and installs one mutation-blocking trigger per protected table;
- valid rows can be inserted across all ten tables;
- direct `UPDATE` and `DELETE` on every table raise the append-only trigger error;
- mismatched execution/user/workspace child scope violates the composite foreign key;
- a second approval consumption violates the unique approval constraint;
- rejected mutations leave every history row and stored digest readable and unchanged.

CI provides an explicitly named `opencanvas_ci` administration database and runs
`pnpm test:postgres` against a randomly created child database. The test never relies on the normal
application database URL implicitly.
