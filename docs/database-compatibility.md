# SQLite / PostgreSQL compatibility audit

Only nonempty DATABASE_URL selects PostgreSQL. LOCAL_DEVELOPMENT governs existing policies, not dialect selection. Production and Vercel require DATABASE_URL; connection failures never fall back to SQLite.

| Dependency surveyed | Compatibility |
|---|---|
| sqlite3 Connection / Row | Isolated in db_backend.py. PostgreSQL rows support column names, dict(row), and positional indexing. |
| ? placeholders | Adapter translates unquoted qmarks to psycopg parameters; quoted literals/comments and literal percent signs are preserved. |
| INSERT OR IGNORE | Replaced by explicit ON CONFLICT(primary_key) DO NOTHING for immutable content registration. |
| INSERT OR REPLACE | Not used. Existing targeted ON CONFLICT upserts and their constraints remain unchanged. |
| AUTOINCREMENT, INTEGER PRIMARY KEY, lastrowid, rowid | Not used. IDs remain application-generated text UUIDs. |
| datetime, CURRENT_TIMESTAMP, JSON/string functions | No SQLite-only functions used. Application-generated UTC timestamps and JSON remain TEXT. |
| Booleans | INTEGER 0/1 with identical CHECK constraints. |
| PRAGMA | SQLite FK, WAL, busy timeout and introspection remain in its adapter. PostgreSQL uses information_schema for CSV columns. |
| Transactions | SQLite BEGIN IMMEDIATE; PostgreSQL READ COMMITTED plus database/schema-wide transaction advisory write lock before request/state reads. Standalone writes use the same lock. |
| Reports / CSV snapshot | PostgreSQL REPEATABLE READ READ ONLY; SQLite BEGIN. |
| Connection.backup | Local SQLite only; PostgreSQL provider backup/restore. |
| Cursors / errors | fetchone/fetchall/iteration/rowcount remain compatible. Constraint errors preserve existing 409 responses, transient lock errors preserve retry responses. Connection details are not exposed. |
| Text ordering | PostgreSQL TEXT COLLATE "C" preserves SQLite bytewise ordering, including UTC strings and UUID tie-breakers. |

PostgreSQL schema preserves all tables, foreign keys, primary/unique/check constraints and indexes. No destructive startup migrations are added. Repeated init-db preserves data and rejects altered same-version content. Existing SQLite schema and report definitions remain unchanged.

UUID lookup, state mutation, successful event and stored response remain within one write transaction. The advisory lock deliberately preserves SQLite single-writer semantics across threads and Vercel instances; it is released on commit/rollback. READ COMMITTED provides fresh state after lock acquisition, so concurrent retries see the first committed response. Changed payloads still receive 409. Existing event/page sequence uniqueness and first-success queries remain unchanged.

Optional PostgreSQL tests reuse the policy/reporting suite: CRUD/restore, retry/concurrency, rollback, exposure, period/sample boundaries, test visitor isolation and CSV. TEST_DATABASE_URL must be a dedicated DB with CREATE SCHEMA permission. Each test creates a UUID-named schema and drops only that schema afterward. No URL means explicit skip, not a simulated PostgreSQL success. This change does not migrate existing SQLite records to PostgreSQL.
