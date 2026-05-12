from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from src.normalize import (
    normalize_candidate_name as _normalize_candidate_name,
    normalize_name_without_latin as _normalize_name_without_latin,
)
from src.normalize import normalize_name as _normalize_name
from src.webapp.identity_checks import find_identity_check_issues

ROOT = Path(__file__).resolve().parents[2]

_ISSUE_TYPE_LABELS = {
    "same_year_multiple": "同一年多場選舉",
    "rank_downgrade": "位階倒退",
    "regional_jump": "跨地區地方選舉",
}
_ISSUE_STATUS_LABELS = {
    "open": "待審",
    "ignored": "沒問題",
    "resolved": "已修正",
    "stale": "已過期",
}
_SEVERITY_LABELS = {
    "critical": "必審",
    "warning": "提醒",
}
_OPERATION_LABELS = {
    "target_existing": "合併到既有人",
    "selected_new": "選取項目建立新 id",
    "others_new": "其他項目建立新 id",
}


@dataclass(frozen=True)
class DatabaseConfig:
    database_url: str
    schema: str = "public"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _build_database_url(values: dict[str, str]) -> str:
    user = os.environ.get("POSTGRES_USER") or values.get("POSTGRES_USER", "")
    password = os.environ.get("POSTGRES_PASSWORD") or values.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST") or values.get("POSTGRES_HOST", "")
    port = os.environ.get("POSTGRES_PORT") or values.get("POSTGRES_PORT", "")
    db = os.environ.get("POSTGRES_DB") or values.get("POSTGRES_DB", "")
    if not (user and host and db):
        return ""
    userinfo = f"{quote(user, safe='')}:{quote(password, safe='')}@" if password else f"{quote(user, safe='')}@"
    port_part = f":{port}" if port else ""
    return f"postgresql://{userinfo}{host}{port_part}/{db}"


def load_database_config(env_path: Path = Path(".env")) -> DatabaseConfig:
    values = _parse_env_file(env_path)
    return DatabaseConfig(
        database_url=_build_database_url(values),
        schema=os.environ.get("POSTGRES_SCHEMA") or values.get("POSTGRES_SCHEMA", "public"),
    )


class Store:
    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self.config = config or load_database_config()
        self._pool: ConnectionPool | None = None

    def open(self) -> None:
        """Initialize the connection pool."""
        if self._pool is not None:
            return

        if not self.config.database_url:
            raise ValueError("PostgreSQL connection is not configured")

        self._pool = ConnectionPool(
            conninfo=self.config.database_url,
            min_size=1,
            max_size=10,
            kwargs={
                "row_factory": dict_row,
                "autocommit": True,
            },
            configure=self._setup_conn,
            open=True,
        )

    def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def connect(self):
        """Get a connection from the pool."""
        if self._pool is None:
            raise RuntimeError("Store is not open. Call open() first.")
        return self._pool.connection()

    def _setup_conn(self, conn: psycopg.Connection) -> None:
        """Common setup for every connection taken from the pool."""
        conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(self.config.schema)))
        conn.execute("set timezone to 'Asia/Taipei'")

    def validate_connection(self) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "select count(*) as n from information_schema.schemata where schema_name = %s",
                (self.config.schema,),
            ).fetchone()
            if row["n"] == 0:
                raise ConnectionError("PostgreSQL schema is not available")

    def init_schema(self) -> None:
        sql_path = ROOT / "db" / "001_init.sql"
        ddl = sql_path.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.config.schema))
            )
            self._setup_conn(conn)
            with conn.transaction():
                conn.execute(ddl)

    def upsert_election(self, election: dict[str, Any]) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO elections(election_id, type, label, path, year, session)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(election_id) DO UPDATE SET
                    type    = EXCLUDED.type,
                    label   = EXCLUDED.label,
                    path    = EXCLUDED.path,
                    year    = EXCLUDED.year,
                    session = EXCLUDED.session
                """,
                (
                    election["election_id"],
                    election["type"],
                    election["label"],
                    str(election["path"]),
                    election.get("year"),
                    election.get("session"),
                ),
            )

    def list_elections(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                select
                    e.election_id,
                    e.type,
                    e.label,
                    e.path,
                    e.year,
                    e.session,
                    e.updated_at,
                    case
                        when count(sr.source_record_id) = 0 then 'todo'
                        when count(r.source_record_id) = count(sr.source_record_id) then 'done'
                        when count(rd.source_record_id) = count(sr.source_record_id) then 'ready'
                        else 'review'
                    end as status,
                    count(sr.source_record_id)::int as imported_count,
                    case
                        when count(r.source_record_id) = count(sr.source_record_id) then 0
                        else (count(sr.source_record_id) - count(rd.source_record_id))::int
                    end as unresolved_count,
                    case
                        when count(r.source_record_id) = count(sr.source_record_id) then count(r.source_record_id)::int
                        else count(rd.source_record_id)::int
                    end as resolved_count,
                    count(case when r.mode in ('manual', 'manual_new') then 1 end)::int as manual_count
                from elections e
                left join source_records sr on sr.election_id = e.election_id
                left join review_decisions rd on rd.source_record_id = sr.source_record_id
                left join resolutions r on r.source_record_id = sr.source_record_id
                group by e.election_id, e.type, e.label, e.path, e.year, e.session, e.updated_at
                order by e.type, e.year nulls last, e.label
                """
            ).fetchall()
        return list(rows)

    def insert_source_record(
        self,
        *,
        source_record_id: str,
        election_id: str,
        payload: dict[str, Any],
        original_kind: str = "unknown",
    ) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO source_records(source_record_id, election_id, name, birthday, payload, original_kind)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(source_record_id) DO UPDATE SET
                    election_id   = EXCLUDED.election_id,
                    name          = EXCLUDED.name,
                    birthday      = EXCLUDED.birthday,
                    payload       = EXCLUDED.payload,
                    original_kind = EXCLUDED.original_kind
                """,
                (
                    source_record_id,
                    election_id,
                    payload["name"],
                    payload.get("birthday"),
                    Jsonb(payload),
                    original_kind,
                ),
            )

    def batch_upsert_source_records(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO source_records(source_record_id, election_id, name, birthday, payload, original_kind)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT(source_record_id) DO UPDATE SET
                            election_id   = EXCLUDED.election_id,
                            name          = EXCLUDED.name,
                            birthday      = EXCLUDED.birthday,
                            payload       = EXCLUDED.payload,
                            original_kind = EXCLUDED.original_kind
                        """,
                        [
                            (
                                r["source_record_id"],
                                r["election_id"],
                                r["payload"]["name"],
                                r["payload"].get("birthday"),
                                Jsonb(r["payload"]),
                                r["original_kind"],
                            )
                            for r in rows
                        ],
                    )

    def batch_upsert_review_decisions(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO review_decisions(source_record_id, election_id, candidate_id, mode)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(source_record_id) DO UPDATE SET
                            candidate_id = EXCLUDED.candidate_id,
                            mode         = EXCLUDED.mode,
                            updated_at   = CURRENT_TIMESTAMP
                        """,
                        [
                            (r["source_record_id"], r["election_id"], r["candidate_id"], r["mode"])
                            for r in rows
                        ],
                    )

    def get_source_record(self, source_record_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT source_record_id, election_id, name, birthday, payload FROM source_records WHERE source_record_id = %s",
                (source_record_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_source_records(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT source_record_id, election_id, name, birthday, payload, original_kind
                FROM source_records
                WHERE election_id = %s
                ORDER BY source_record_id
                """,
                (election_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_review_decision(
        self,
        *,
        source_record_id: str,
        election_id: str,
        candidate_id: str,
        mode: str,
    ) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO review_decisions(source_record_id, election_id, candidate_id, mode)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(source_record_id) DO UPDATE SET
                    candidate_id = EXCLUDED.candidate_id,
                    mode         = EXCLUDED.mode,
                    updated_at   = CURRENT_TIMESTAMP
                """,
                (source_record_id, election_id, candidate_id, mode),
            )

    def list_review_decisions(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT source_record_id, election_id, candidate_id, mode, updated_at
                FROM review_decisions
                WHERE election_id = %s
                ORDER BY source_record_id
                """,
                (election_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_candidates_by_name(self, name: str) -> list[dict[str, Any]]:
        normalized = _normalize_candidate_name(name)
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.birthday,
                       ce.year, ce.type, ce.region, ce.party,
                       ce.elected, ce.session, ce.ticket, ce.order_id
                FROM candidates c
                LEFT JOIN candidate_elections ce ON ce.candidate_id = c.id
                WHERE c.name = %s
                ORDER BY c.id, ce.year NULLS LAST
                """,
                (normalized,),
            ).fetchall()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            cid = row["id"]
            if cid not in grouped:
                grouped[cid] = {
                    "id": row["id"],
                    "name": row["name"],
                    "birthday": row["birthday"],
                    "elections": [],
                }
            if row["year"] is not None:
                election = {k: row[k] for k in ("year", "type", "region", "party", "elected", "session", "ticket", "order_id") if row[k] is not None}
                grouped[cid]["elections"].append(election)
        return list(grouped.values())

    def list_candidates_by_names(self, names: set[str]) -> dict[str, list[dict[str, Any]]]:
        """Batch lookup: returns {normalized_name: [candidate, ...]}."""
        if not names:
            return {}
        normalized = list({_normalize_candidate_name(n) for n in names})
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.birthday,
                       ce.year, ce.type, ce.region, ce.party,
                       ce.elected, ce.session, ce.ticket, ce.order_id
                FROM candidates c
                LEFT JOIN candidate_elections ce ON ce.candidate_id = c.id
                WHERE c.name = ANY(%s)
                ORDER BY c.id, ce.year NULLS LAST
                """,
                (normalized,),
            ).fetchall()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            cid = row["id"]
            if cid not in grouped:
                grouped[cid] = {"id": cid, "name": row["name"], "birthday": row["birthday"], "elections": []}
            if row["year"] is not None:
                election = {k: row[k] for k in ("year", "type", "region", "party", "elected", "session", "ticket", "order_id") if row[k] is not None}
                grouped[cid]["elections"].append(election)

        by_name: dict[str, list[dict[str, Any]]] = {}
        for c in grouped.values():
            by_name.setdefault(c["name"], []).append(c)
        return by_name

    def list_candidates_by_name_without_latin(self, name: str) -> list[dict[str, Any]]:
        normalized = _normalize_name_without_latin(name)
        if not normalized:
            return []
        candidates = self.list_candidates_with_elections()
        return [
            candidate
            for candidate in candidates
            if _normalize_name_without_latin(candidate["name"]) == normalized
        ]

    def list_candidates_with_elections(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT
                    c.id, c.name, c.birthday,
                    ce.year, ce.type, ce.region, ce.party,
                    ce.elected, ce.session, ce.ticket, ce.order_id
                FROM candidates c
                LEFT JOIN candidate_elections ce ON ce.candidate_id = c.id
                ORDER BY c.id, ce.year NULLS LAST
                """
            ).fetchall()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            cid = row["id"]
            if cid not in grouped:
                grouped[cid] = {
                    "id": cid,
                    "name": row["name"],
                    "birthday": row["birthday"],
                    "elections": [],
                }
            if row["year"] is not None:
                election = {k: row[k] for k in ("year", "type", "region", "party", "elected", "session", "ticket", "order_id") if row[k] is not None}
                grouped[cid]["elections"].append(election)

        return list(grouped.values())

    def list_committed_candidates_with_source_records(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT
                    c.id, c.name, c.birthday,
                    r.source_record_id, r.election_id,
                    sr.payload
                FROM candidates c
                JOIN resolutions r ON r.candidate_id = c.id
                JOIN source_records sr ON sr.source_record_id = r.source_record_id
                ORDER BY c.id, (sr.payload->>'year')::int NULLS LAST, sr.payload->>'type', sr.payload->>'region'
                """
            ).fetchall()
        return self._group_committed_candidate_rows(rows)

    def refresh_identity_check_issues(self) -> int:
        issues = find_identity_check_issues(self.list_committed_candidates_with_source_records())
        issue_keys = [issue["issue_key"] for issue in issues]
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                for issue in issues:
                    conn.execute(
                        """
                        INSERT INTO identity_check_issues
                            (issue_key, candidate_id, issue_type, severity, summary, source_record_ids, election_refs)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(issue_key) DO UPDATE SET
                            candidate_id      = EXCLUDED.candidate_id,
                            issue_type        = EXCLUDED.issue_type,
                            severity          = EXCLUDED.severity,
                            summary           = EXCLUDED.summary,
                            source_record_ids = EXCLUDED.source_record_ids,
                            election_refs     = EXCLUDED.election_refs,
                            status            = CASE
                                WHEN identity_check_issues.status = 'stale' THEN 'open'
                                ELSE identity_check_issues.status
                            END,
                            updated_at        = CURRENT_TIMESTAMP
                        """,
                        (
                            issue["issue_key"],
                            issue["candidate_id"],
                            issue["issue_type"],
                            issue["severity"],
                            issue["summary"],
                            issue["source_record_ids"],
                            Jsonb(issue["election_refs"]),
                        ),
                    )
                if issue_keys:
                    conn.execute(
                        """
                        UPDATE identity_check_issues
                        SET status = 'stale'
                        WHERE status = 'open'
                          AND NOT (issue_key = ANY(%s))
                        """,
                        (issue_keys,),
                    )
                else:
                    conn.execute("UPDATE identity_check_issues SET status = 'stale' WHERE status = 'open'")
        return len(issues)

    def list_identity_check_issues(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT i.*, c.name, c.birthday
                FROM identity_check_issues i
                JOIN candidates c ON c.id = i.candidate_id
                ORDER BY
                    CASE i.status WHEN 'open' THEN 0 WHEN 'stale' THEN 1 WHEN 'resolved' THEN 2 ELSE 3 END,
                    CASE i.severity WHEN 'critical' THEN 0 ELSE 1 END,
                    i.updated_at DESC,
                    i.id DESC
                """
            ).fetchall()
        return [self._decorate_identity_issue(dict(row)) for row in rows]

    def get_identity_check_detail(self, issue_id: int) -> dict[str, Any] | None:
        issue = self._get_identity_issue(issue_id)
        if issue is None:
            return None
        candidate = self._get_committed_candidate(issue["candidate_id"])
        if candidate is None:
            return None
        nearby = self._nearby_candidates(candidate)
        operations = self.list_identity_fix_operations(issue_id=issue_id)
        return {
            "issue": issue,
            "candidate": candidate,
            "records": candidate["elections"],
            "nearby_candidates": nearby,
            "operations": operations,
        }

    def update_identity_check_status(self, issue_id: int, status: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE identity_check_issues SET status = %s WHERE id = %s",
                (status, issue_id),
            )

    def preview_identity_fix(
        self,
        *,
        issue_id: int,
        action: str,
        source_record_ids: list[str],
        target_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        issue = self._get_identity_issue(issue_id)
        if issue is None:
            return {"error": "找不到待審項目"}
        plan = self._identity_fix_plan(issue, action, source_record_ids, target_candidate_id)
        if plan.get("error"):
            return plan
        return {
            "action": action,
            "action_label": _OPERATION_LABELS.get(action, action),
            "source_record_ids": plan["moved_source_record_ids"],
            "target_candidate_id": plan["target_candidate_id"],
            "after_candidates": plan["after_candidates"],
        }

    def apply_identity_fix(
        self,
        *,
        issue_id: int,
        action: str,
        source_record_ids: list[str],
        target_candidate_id: str | None = None,
    ) -> int:
        issue = self._get_identity_issue(issue_id)
        if issue is None:
            raise ValueError("找不到待審項目")
        plan = self._identity_fix_plan(issue, action, source_record_ids, target_candidate_id)
        if plan.get("error"):
            raise ValueError(plan["error"])

        source_candidate_id = issue["candidate_id"]
        affected_ids = plan["affected_candidate_ids"]
        before = self._snapshot_candidates(affected_ids)

        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                if plan["create_candidate"]:
                    conn.execute(
                        """
                        INSERT INTO candidates(id, name, birthday)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(id) DO NOTHING
                        """,
                        (
                            plan["target_candidate_id"],
                            plan["new_candidate_name"],
                            plan["new_candidate_birthday"],
                        ),
                    )

                conn.execute(
                    """
                    UPDATE resolutions
                    SET candidate_id = %s
                    WHERE candidate_id = %s
                      AND source_record_id = ANY(%s)
                    """,
                    (plan["target_candidate_id"], source_candidate_id, plan["moved_source_record_ids"]),
                )
                self._sync_candidate_elections(conn, affected_ids)
                after = self._snapshot_candidates(affected_ids, conn=conn)
                row = conn.execute(
                    """
                    INSERT INTO identity_fix_operations
                        (issue_id, operation, source_candidate_id, target_candidate_id,
                         moved_source_record_ids, before_snapshot, after_snapshot)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        issue_id,
                        action,
                        source_candidate_id,
                        plan["target_candidate_id"],
                        plan["moved_source_record_ids"],
                        Jsonb(before),
                        Jsonb(after),
                    ),
                ).fetchone()
                conn.execute(
                    "UPDATE identity_check_issues SET status = 'resolved' WHERE id = %s",
                    (issue_id,),
                )
        return int(row["id"])

    def list_identity_fix_operations(self, *, issue_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            if issue_id is None:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM identity_fix_operations
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM identity_fix_operations
                    WHERE issue_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (issue_id, limit),
                ).fetchall()
        return [self._decorate_identity_operation(dict(row)) for row in rows]

    def _group_committed_candidate_rows(self, rows) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            cid = row["id"]
            if cid not in grouped:
                grouped[cid] = {
                    "id": row["id"],
                    "name": row["name"],
                    "birthday": row["birthday"],
                    "elections": [],
                }
            payload = row["payload"]
            election = {
                "source_record_id": row["source_record_id"],
                "election_id": row["election_id"],
                "year": payload.get("year"),
                "type": payload.get("type"),
                "region": payload.get("region"),
                "party": payload.get("party"),
                "elected": payload.get("elected"),
                "session": payload.get("session"),
                "ticket": payload.get("ticket"),
                "order_id": payload.get("order_id"),
                "birthday": payload.get("birthday"),
                "name": payload.get("name"),
            }
            grouped[cid]["elections"].append(election)
        return list(grouped.values())

    def _get_identity_issue(self, issue_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                SELECT i.*, c.name, c.birthday
                FROM identity_check_issues i
                JOIN candidates c ON c.id = i.candidate_id
                WHERE i.id = %s
                """,
                (issue_id,),
            ).fetchone()
        return self._decorate_identity_issue(dict(row)) if row else None

    def _decorate_identity_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        issue["issue_type_label"] = _ISSUE_TYPE_LABELS.get(issue["issue_type"], issue["issue_type"])
        issue["status_label"] = _ISSUE_STATUS_LABELS.get(issue["status"], issue["status"])
        issue["severity_label"] = _SEVERITY_LABELS.get(issue["severity"], issue["severity"])
        return issue

    def _decorate_identity_operation(self, row: dict[str, Any]) -> dict[str, Any]:
        row["operation_label"] = _OPERATION_LABELS.get(row["operation"], row["operation"])
        return row

    def _get_committed_candidate(self, candidate_id: str, conn=None) -> dict[str, Any] | None:
        close_conn = False
        if conn is None:
            close_conn = True
            ctx = self.connect()
            conn = ctx.__enter__()
            self._setup_conn(conn)
        try:
            rows = conn.execute(
                """
                SELECT
                    c.id, c.name, c.birthday,
                    r.source_record_id, r.election_id,
                    sr.payload
                FROM candidates c
                LEFT JOIN resolutions r ON r.candidate_id = c.id
                LEFT JOIN source_records sr ON sr.source_record_id = r.source_record_id
                WHERE c.id = %s
                ORDER BY (sr.payload->>'year')::int NULLS LAST, sr.payload->>'type', sr.payload->>'region'
                """,
                (candidate_id,),
            ).fetchall()
            if not rows:
                return None
            real_rows = [r for r in rows if r["source_record_id"] is not None]
            if not real_rows:
                row = rows[0]
                return {"id": row["id"], "name": row["name"], "birthday": row["birthday"], "elections": []}
            return self._group_committed_candidate_rows(real_rows)[0]
        finally:
            if close_conn:
                ctx.__exit__(None, None, None)

    def _nearby_candidates(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        birthday = candidate.get("birthday")
        if birthday is None:
            return []
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT id
                FROM candidates
                WHERE name = %s
                  AND id <> %s
                  AND birthday IS NOT NULL
                  AND ABS(birthday - %s) = 1
                ORDER BY id
                """,
                (candidate["name"], candidate["id"], birthday),
            ).fetchall()
        nearby = []
        for row in rows:
            item = self._get_committed_candidate(row["id"])
            if item is not None:
                nearby.append(item)
        return nearby

    def _identity_fix_plan(
        self,
        issue: dict[str, Any],
        action: str,
        source_record_ids: list[str],
        target_candidate_id: str | None,
    ) -> dict[str, Any]:
        source = self._get_committed_candidate(issue["candidate_id"])
        if source is None:
            return {"error": "找不到候選人"}
        source_ids = {e["source_record_id"] for e in source["elections"]}
        selected = [sid for sid in source_record_ids if sid in source_ids]
        if not selected:
            return {"error": "請至少選擇一筆 election"}

        create_candidate = False
        new_candidate_name = source["name"]
        new_candidate_birthday = source["birthday"]

        if action == "target_existing":
            if not target_candidate_id:
                return {"error": "請選擇要合併到哪一個候選人"}
            target = self._get_committed_candidate(target_candidate_id)
            if target is None or target["id"] == source["id"]:
                return {"error": "合併目標無效"}
            moved = selected
        elif action == "selected_new":
            target_candidate_id = self._next_available_candidate_id(source["id"])
            target = {"id": target_candidate_id, "name": source["name"], "birthday": source["birthday"], "elections": []}
            create_candidate = True
            moved = selected
        elif action == "others_new":
            moved = [sid for sid in source_ids if sid not in selected]
            if not moved:
                return {"error": "沒有其他 elections 可以拆出"}
            target_candidate_id = self._next_available_candidate_id(source["id"])
            target = {"id": target_candidate_id, "name": source["name"], "birthday": source["birthday"], "elections": []}
            create_candidate = True
        else:
            return {"error": "修正方式無效"}

        if len(moved) == len(source_ids):
            return {"error": "修正後原 candidate 會沒有任何 elections"}

        moved_set = set(moved)
        source_after = {
            **source,
            "elections": [e for e in source["elections"] if e["source_record_id"] not in moved_set],
        }
        target_after = {
            **target,
            "elections": sorted(
                target["elections"] + [e for e in source["elections"] if e["source_record_id"] in moved_set],
                key=lambda e: (e.get("year") or 0, e.get("type") or "", e.get("region") or ""),
            ),
        }
        after_candidates = [c for c in (source_after, target_after) if c["elections"]]
        collision = self._candidate_collision(after_candidates)
        if collision:
            return {"error": collision}

        return {
            "target_candidate_id": target_candidate_id,
            "moved_source_record_ids": moved,
            "affected_candidate_ids": sorted({source["id"], target_candidate_id}),
            "after_candidates": after_candidates,
            "create_candidate": create_candidate,
            "new_candidate_name": new_candidate_name,
            "new_candidate_birthday": new_candidate_birthday,
        }

    def _candidate_collision(self, candidates: list[dict[str, Any]]) -> str:
        for candidate in candidates:
            seen = set()
            for election in candidate["elections"]:
                key = (election.get("year"), election.get("type"), election.get("region"))
                if key in seen:
                    return f"{candidate['id']} 合併後會出現重複 election"
                seen.add(key)
        return ""

    def _next_available_candidate_id(self, base_id: str) -> str:
        suffixes = [chr(i) for i in range(ord("a"), ord("z") + 1)] + [str(i) for i in range(1, 100)]
        with self.connect() as conn:
            self._setup_conn(conn)
            for suffix in suffixes:
                candidate_id = f"{base_id}{suffix}"
                if not conn.execute("SELECT 1 FROM candidates WHERE id = %s", (candidate_id,)).fetchone():
                    return candidate_id
        raise ValueError("找不到可用的新 candidate id")

    def _snapshot_candidates(self, candidate_ids: list[str], conn=None) -> list[dict[str, Any]]:
        if conn is not None:
            snapshot = []
            for candidate_id in candidate_ids:
                candidate = self._get_committed_candidate(candidate_id, conn=conn)
                if candidate is not None:
                    snapshot.append(candidate)
            return snapshot

        with self.connect() as managed_conn:
            self._setup_conn(managed_conn)
            return self._snapshot_candidates(candidate_ids, conn=managed_conn)

    def _sync_candidate_elections(self, conn, candidate_ids: list[str]) -> None:
        for candidate_id in candidate_ids:
            conn.execute("DELETE FROM candidate_elections WHERE candidate_id = %s", (candidate_id,))
            rows = conn.execute(
                """
                SELECT sr.payload
                FROM resolutions r
                JOIN source_records sr ON sr.source_record_id = r.source_record_id
                WHERE r.candidate_id = %s
                ORDER BY (sr.payload->>'year')::int NULLS LAST, sr.payload->>'type', sr.payload->>'region'
                """,
                (candidate_id,),
            ).fetchall()
            for row in rows:
                payload = row["payload"]
                if not (payload.get("year") and payload.get("type") and payload.get("region")):
                    continue
                conn.execute(
                    """
                    INSERT INTO candidate_elections
                        (candidate_id, year, type, region, party, elected, session, ticket, order_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(candidate_id, year, type, region) DO UPDATE SET
                        party   = EXCLUDED.party,
                        elected = EXCLUDED.elected,
                        session = EXCLUDED.session,
                        ticket  = EXCLUDED.ticket,
                        order_id = EXCLUDED.order_id
                    """,
                    (
                        candidate_id,
                        payload.get("year"),
                        payload.get("type"),
                        payload.get("region"),
                        payload.get("party"),
                        payload.get("elected"),
                        payload.get("session"),
                        payload.get("ticket"),
                        payload.get("order_id"),
                    ),
                )

    def commit_election(
        self,
        *,
        election_id: str,
        decisions: dict[str, dict[str, Any]],
        source_records_map: dict[str, dict[str, Any]],
    ) -> tuple[int, int]:
        """Batch write resolutions + candidates + candidate_elections in one transaction.
        Returns (auto_count, manual_count).
        """
        auto = manual = 0

        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                for src_id, decision in decisions.items():
                    candidate_id = decision["candidate_id"]
                    mode = decision["mode"]
                    payload = source_records_map[src_id]

                    conn.execute(
                        """
                        INSERT INTO resolutions(source_record_id, election_id, candidate_id, mode)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(source_record_id) DO UPDATE SET
                            candidate_id = EXCLUDED.candidate_id,
                            mode         = EXCLUDED.mode
                        """,
                        (src_id, election_id, candidate_id, mode),
                    )
                    conn.execute(
                        """
                        INSERT INTO candidates(id, name, birthday)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(id) DO NOTHING
                        """,
                        (candidate_id, _normalize_candidate_name(payload["name"]), payload.get("birthday")),
                    )
                    conn.execute(
                        """
                        INSERT INTO candidate_elections
                            (candidate_id, year, type, region, party, elected, session, ticket, order_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(candidate_id, year, type, region) DO UPDATE SET
                            party   = EXCLUDED.party,
                            elected = EXCLUDED.elected
                        """,
                        (
                            candidate_id,
                            payload.get("year"),
                            payload.get("type"),
                            payload.get("region"),
                            payload.get("party"),
                            payload.get("elected"),
                            payload.get("session"),
                            payload.get("ticket"),
                            payload.get("order_id"),
                        ),
                    )
                    if mode in ("auto", "new"):
                        auto += 1
                    else:
                        manual += 1

                conn.execute(
                    "DELETE FROM review_decisions WHERE election_id = %s",
                    (election_id,),
                )

        return auto, manual

    def list_resolutions(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT r.source_record_id, r.candidate_id, r.mode, sr.name
                FROM resolutions r
                JOIN source_records sr ON sr.source_record_id = r.source_record_id
                WHERE r.election_id = %s
                ORDER BY sr.name
                """,
                (election_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_election(self, election_id: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute("delete from elections where election_id = %s", (election_id,))

    def delete_candidate(self, candidate_id: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute("DELETE FROM candidates WHERE id = %s", (candidate_id,))

    def rename_candidate(self, old_id: str, new_id: str, new_birthday: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            if conn.execute("SELECT 1 FROM candidates WHERE id = %s", (new_id,)).fetchone():
                raise ValueError(f"候選人 {new_id} 已存在，id rename 失敗，需人工處理")
            with conn.transaction():
                conn.execute(
                    "INSERT INTO candidates(id, name, birthday) SELECT %s, name, %s FROM candidates WHERE id = %s",
                    (new_id, new_birthday, old_id),
                )
                conn.execute(
                    "UPDATE candidate_elections SET candidate_id = %s WHERE candidate_id = %s",
                    (new_id, old_id),
                )
                conn.execute(
                    "UPDATE resolutions SET candidate_id = %s WHERE candidate_id = %s",
                    (new_id, old_id),
                )
                conn.execute(
                    "UPDATE review_decisions SET candidate_id = %s WHERE candidate_id = %s",
                    (new_id, old_id),
                )
                conn.execute("DELETE FROM candidates WHERE id = %s", (old_id,))
