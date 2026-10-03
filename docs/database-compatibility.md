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

## Transaction pooling and failure investigation

Neon pooled endpoints use transaction pooling. A successful session SET followed by a successful SELECT once does not establish that later transactions use that server session. [PgBouncer's compatibility table](https://www.pgbouncer.org/features.html) excludes session SET/RESET from transaction pooling. The adapter therefore applies schema and 5s/30s timeouts with SET LOCAL **inside every transaction**, before advisory lock acquisition or application queries. Standalone reads/writes get short transactions; explicit write/read isolation, atomic state/event commits and transaction advisory locks retain their purpose. Schema names retain regex validation and sql.Identifier quoting. No automatic reconnect, statement replay, timeout increase or expectation weakening is added.

get_db caches in Flask g for one application context, not globally. Concurrent workers create independent contexts and connections; app-context teardown closes each. A manually pushed long-lived application context can intentionally keep one connection within that context, so concurrency tests do not push one shared context across workers. Setup CREATE SCHEMA and cleanup DROP SCHEMA now use separate short-lived control connections.

Development/testing errors include an allowlisted stage, exception class, SQLSTATE, closed flag, connection status and transaction status. They never print SQL parameters, URLs, hosts, usernames or passwords. A failed rollback during another failure adds safe evidence to the original exception and closes the unusable connection; it does not hide the failed operation or retry it. An independent rollback failure is still raised.

The two-tab test previously omitted the second page's required book_view event. SQLite independently reproduced [200,403] without any DB loss. The test now records book_view before simultaneous short submissions; expected [200,200], one review and one first-success event remain unchanged.

The supplied 5504-second run has no per-test durations or underlying operation SQLSTATE, so its exact timing breakdown and server-disconnect cause are not yet established. HTTP tests issue many SQL round trips and connections, especially the 50-visitor scenario. There is no application retry loop in this pytest path. Do not infer repeated five-second waits merely from elapsed time. Collect durations and the new timing counters to distinguish connection latency, SQL time and advisory lock waits. Timings are nested: advisory-lock seconds are included in BEGIN-write/standalone-write seconds and must not be added twice.

Run only the three failing PostgreSQL cases first, with TEST_DATABASE_URL already set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs --durations=0 --tb=short `
  tests/test_postgres.py::test_concurrent_retry_and_distinct_tab_submissions `
  tests/test_postgres.py::test_two_tabs_concurrently_preserve_first_success `
  tests/test_postgres.py::test_fifty_test_visitors_do_not_satisfy_experiment_sample `
  --junitxml=artifacts/postgres-targeted.xml -o junit_family=legacy
```

The XML properties contain per-test stage call counts/seconds (no connection information); failed reports also show the PostgreSQL timing section. Do not use --showlocals when sharing failure output, since pytest local variables can include a URL. To profile the remaining PostgreSQL cases later, run `python -m pytest tests/test_postgres.py -q -rs --durations=0 --tb=short`. No URL still explicitly skips integration tests.

## Same-UUID timeout and latency optimization

The targeted Neon run established SQLSTATE 55P03 at the transaction advisory lock. The old lock key was and remains `hashtextextended(current_schema() || ':chaek-ex-write', 0)`; PostgreSQL advisory locks are database-local. It is a transaction lock (`pg_advisory_xact_lock`), released by COMMIT/ROLLBACK, not a session lock. The global mutation lock is retained because mutations validate other visitors' review state as well as their own state. The timeout remains five seconds.

Previously even retries waited for that lock before checking requests, and refreshed response state while holding it. For a first short submission by a visitor with no other participation, the old locked path included 21 SELECTs (11 validation/event-context reads and 10 response-state reads), three INSERTs and COMMIT. The supplied aggregate averages are 24.386/77=0.317 seconds per SELECT and 8.618/31=0.278 per INSERT. Applying those averages gives approximately 7.7 seconds including COMMIT. This is an explanatory estimate, not a measured per-request hold duration: the aggregates mix setup, concurrency and waiting.

Now a read preflight looks up a completed UUID, validates its fingerprint/owner and returns the current response state without a write lock. A miss is rechecked under the same advisory lock. Immutable page/book_view validation and content reads precede the lock; mutation-related mutable state is still checked under it. State, successful event and requests response are committed atomically. The response state is then read in a separate consistent read transaction. A first short submission's locked path is three SELECTs (requests, prior review, combined event context), three INSERTs and COMMIT. Event context plus prior-short status use one query, eligibility uses one query, and the four independent state reads are batched. Current invalid/cohort/ownership checks and first-success/page-order semantics are unchanged.

All PostgreSQL transaction-local settings are pipelined with BEGIN, while the advisory lock remains a separately awaited/measured operation. Schema DDL and immutable content registration use pipelines too. One init-db still executes 15 schema statements, six version comparisons and twelve seed INSERTs (six content versions), and initialization is still performed twice. This preserves 66 logical application SQL statements across both runs, grouped into batches instead of 66 sequential waits. Individual init-db durations, SQL counts, lock waits and connection close time are recorded.

The exact old 1919.98-second breakdown cannot be recovered from the earlier partial counters. The HTTP workload itself is verified: each of 50 Participant constructions makes three redirected bootstrap GETs plus one book_view POST, followed by emoji and short POSTs. That is 300 actual Flask requests and 301 DB acquisitions/closes including the final reporting context. Both report functions are called once at the end; init-db is not called per request, and there are no external HTTP/API calls or Python sleep/retry loops in that path. The optimized SQLite measurement sent 2516 application SQL statements (1416 standalone SELECT, 500 INSERT, 600 batched SQL statements), plus transaction management. These counts describe the application workload, not Neon elapsed time or wire-level round trips.

New profiling separates pytest setup/body/cleanup, entire HTTP duration including Flask teardown, bootstrap/book_view/emoji/short client time, DB acquisition, individual SQL/batch duration, close duration, advisory lock wait and actual lock-held time. `SQL sent` also counts adapter-generated BEGIN/SET LOCAL/lock statements; protocol-managed psycopg transaction commands are separate. Timing categories are nested and must not all be summed. Per-body HTTP DB time is a subset of HTTP wall time; direct reporting DB time is outside HTTP. Pipeline enqueue time is not equivalent to network synchronization time: use batch duration for that wait.

After the targeted command above, print the numerical breakdown without reading captured exception text:

```powershell
.\.venv\Scripts\python.exe scripts/summarize_postgres_profile.py artifacts/postgres-targeted.xml
```

The summary reports body wall = HTTP wall + direct DB/report wall + remaining outside-HTTP/DB time. Within HTTP it separates DB from framework/unprofiled time. The remaining wall time cannot automatically be labelled Python CPU or network latency. Region-to-region latency remains a hypothesis until the new Neon measurements quantify those categories. No automatic retries, sleeps, timeout increase, lock removal or changed status expectations were used to hide the issue.
