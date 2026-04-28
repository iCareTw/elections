---
name: elections-db
description: Access the local PostgreSQL database for the elections project. Use when Codex needs to inspect or clear the `idontcare` database, the `elections` schema, identity ui DB state, raw source records, committed candidate identity decisions, candidate mappings, or local identity ui operation and error logs for debugging.
---

# Idontcare Elections DB

## Scope

Use this skill for read-first debugging of identity ui data. Connection parameters live in the project `.env`.

Expected defaults:

- Database: `POSTGRES_DB=idontcare`
- Schema: `POSTGRES_SCHEMA=elections`
- Tables: `elections`, `source_records`, `resolutions`, `candidates`, `candidate_elections`
- Logs: `logs/operations.log`, `logs/errors.log`

Do not print `POSTGRES_PASSWORD` or a full database URL. Do not mutate DB state unless the user explicitly asks for a write.

## Clear Table Data

When the user explicitly asks to clear or reset DB table data, use the bundled script instead of rewriting ad hoc `DELETE FROM` statements:

```bash
uv run python .agents/skills/elections-db/scripts/clear_table_data.py --yes
```

The script deletes rows only. It does not drop tables. Without `--yes`, it runs in dry-run mode and prints current row counts.

## Connect

Prefer the project Store because it already parses `.env`, builds the PostgreSQL URL, checks the schema, and sets `search_path` to `POSTGRES_SCHEMA`:

```bash
uv run python - <<'PY'
from src.webapp.store import Store

with Store().connect() as conn:
    print(conn.execute("select current_database() as db, current_schema() as schema").fetchone())
PY
```

If you need an ad hoc query, keep it parameterized:

```bash
uv run python - <<'PY'
from src.webapp.store import Store

sql = """
select election_id, type, label, year, session
from elections
order by type, year nulls last, label
limit %s
"""

with Store().connect() as conn:
    for row in conn.execute(sql, (20,)).fetchall():
        print(dict(row))
PY
```

## Debug Workflow

1. Validate connection and schema with `select current_database(), current_schema()`.
2. Inspect election status before drilling into candidates or decisions.
3. Use `source_records` for imported raw records.
4. Use `resolutions` for committed identity decisions only.
5. Use `candidates` and `candidate_elections` for the current business mapping.
6. Use `logs/operations.log` and `logs/errors.log` for identity ui operation summaries and exceptions.

IMPORTANT: review choices kept in the browser session are not in DB until `Commit to DB`. Do not assume uncommitted decisions can be recovered from `resolutions`.

## Useful Queries

Election status:

```sql
select
    e.election_id,
    e.type,
    e.label,
    e.year,
    e.session,
    count(sr.source_record_id)::int as imported_count,
    count(sr.source_record_id) filter (where r.source_record_id is null)::int as unresolved_count,
    count(r.source_record_id)::int as resolved_count
from elections e
left join source_records sr on sr.election_id = e.election_id
left join resolutions r on r.source_record_id = sr.source_record_id
group by e.election_id, e.type, e.label, e.year, e.session
order by e.type, e.year nulls last, e.label;
```

Records needing committed resolution:

```sql
select sr.source_record_id, sr.election_id, sr.name, sr.birthday, sr.payload
from source_records sr
left join resolutions r on r.source_record_id = sr.source_record_id
where sr.election_id = %s
  and r.source_record_id is null
order by sr.source_record_id
limit %s;
```

Committed decisions for one election:

```sql
select
    sr.source_record_id,
    sr.name as source_name,
    sr.birthday as source_birthday,
    r.mode,
    r.candidate_id,
    c.name as candidate_name,
    c.birthday as candidate_birthday,
    sr.payload
from resolutions r
join source_records sr on sr.source_record_id = r.source_record_id
left join candidates c on c.id = r.candidate_id
where r.election_id = %s
order by sr.source_record_id
limit %s;
```

Candidate mapping by name:

```sql
select
    c.id,
    c.name,
    c.birthday,
    ce.year,
    ce.type,
    ce.region,
    ce.party,
    ce.elected,
    ce.session,
    ce.ticket,
    ce.order_id
from candidates c
left join candidate_elections ce on ce.candidate_id = c.id
where c.name = %s
order by c.id, ce.year nulls last;
```

## Operation Logs

The current identity ui design uses file-based logging instead of an `operation_logs` table.

Use:

```bash
tail -n 80 logs/operations.log
tail -n 80 logs/errors.log
```

Typical `operations.log` lines include load, commit, and build summaries. Use `errors.log` for tracebacks and failed requests.
