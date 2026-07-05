from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

_clog = logging.getLogger("candidates")

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
    "stale": "已自動解除",
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
        # 套用基線 schema (001) 與後續「schema-agnostic 且冪等」的 migration.
        # 002 寫死 elections schema, 屬正式 DB 專用, 不在此套用.
        ddl_files = ("001_init.sql", "004_rename_birthday_to_birthyear.sql", "005_voter_guide.sql")
        with self.connect() as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.config.schema))
            )
            self._setup_conn(conn)
            with conn.transaction():
                for name in ddl_files:
                    conn.execute((ROOT / "db" / name).read_text(encoding="utf-8"))

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
                INSERT INTO source_records(source_record_id, election_id, name, birthyear, payload, original_kind)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(source_record_id) DO UPDATE SET
                    election_id   = EXCLUDED.election_id,
                    name          = EXCLUDED.name,
                    birthyear      = EXCLUDED.birthyear,
                    payload       = EXCLUDED.payload,
                    original_kind = EXCLUDED.original_kind
                """,
                (
                    source_record_id,
                    election_id,
                    payload["name"],
                    payload.get("birthyear"),
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
                        INSERT INTO source_records(source_record_id, election_id, name, birthyear, payload, original_kind)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT(source_record_id) DO UPDATE SET
                            election_id   = EXCLUDED.election_id,
                            name          = EXCLUDED.name,
                            birthyear      = EXCLUDED.birthyear,
                            payload       = EXCLUDED.payload,
                            original_kind = EXCLUDED.original_kind
                        """,
                        [
                            (
                                r["source_record_id"],
                                r["election_id"],
                                r["payload"]["name"],
                                r["payload"].get("birthyear"),
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
                "SELECT source_record_id, election_id, name, birthyear, payload FROM source_records WHERE source_record_id = %s",
                (source_record_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_source_records(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT source_record_id, election_id, name, birthyear, payload, original_kind
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
                SELECT c.id, c.name, c.birthyear,
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
                    "birthyear": row["birthyear"],
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
                SELECT c.id, c.name, c.birthyear,
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
                grouped[cid] = {"id": cid, "name": row["name"], "birthyear": row["birthyear"], "elections": []}
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
                    c.id, c.name, c.birthyear, c.alias_names,
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
                    "birthyear": row["birthyear"],
                }
                if row["alias_names"]:
                    grouped[cid]["alias_names"] = list(row["alias_names"])
                grouped[cid]["elections"] = []
            if row["year"] is not None:
                election = {k: row[k] for k in ("year", "type", "region", "party", "elected", "session", "ticket", "order_id") if row[k] is not None}
                grouped[cid]["elections"].append(election)

        return list(grouped.values())

    def search_candidates_for_aliases(self, query: str = "") -> list[dict[str, Any]]:
        query = query.strip()
        pattern = f"%{query}%"
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT id, name, birthyear, alias_names
                FROM candidates
                WHERE %s = ''
                   OR name ILIKE %s
                   OR id ILIKE %s
                   OR EXISTS (
                       SELECT 1 FROM unnest(alias_names) AS alias_name
                       WHERE alias_name ILIKE %s
                   )
                ORDER BY name, birthyear NULLS LAST, id
                LIMIT 200
                """,
                (query, pattern, pattern, pattern),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_candidate_alias(self, candidate_id: str, alias_name: str) -> None:
        alias_name = alias_name.strip()
        if not alias_name:
            raise ValueError("請輸入別名")
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT name, alias_names FROM candidates WHERE id = %s",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise ValueError("找不到指定人物")
            if alias_name == row["name"]:
                raise ValueError("別名不可與目前姓名相同")
            if alias_name not in row["alias_names"]:
                conn.execute(
                    "UPDATE candidates SET alias_names = array_append(alias_names, %s) WHERE id = %s",
                    (alias_name, candidate_id),
                )
                _clog.info("ADD_ALIAS candidate_id=%s name=%s alias=%s", candidate_id, row["name"], alias_name)

    def remove_candidate_alias(self, candidate_id: str, alias_name: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE candidates SET alias_names = array_remove(alias_names, %s) WHERE id = %s",
                (alias_name, candidate_id),
            )
        _clog.info("REMOVE_ALIAS candidate_id=%s alias=%s", candidate_id, alias_name)

    def list_committed_candidates_with_source_records(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT
                    c.id, c.name, c.birthyear,
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
                SELECT i.*, c.name, c.birthyear,
                       ARRAY(
                           SELECT DISTINCT ce.type
                           FROM candidate_elections ce
                           WHERE ce.candidate_id = i.candidate_id
                       ) AS candidate_election_types
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

    def ignore_candidate_open_issues(self, issue_id: int) -> int:
        """Mark every still-open issue of the issue's candidate as ignored."""
        with self.connect() as conn:
            self._setup_conn(conn)
            result = conn.execute(
                """
                UPDATE identity_check_issues
                SET status = 'ignored'
                WHERE status = 'open'
                  AND candidate_id = (
                      SELECT candidate_id FROM identity_check_issues WHERE id = %s
                  )
                """,
                (issue_id,),
            )
            return result.rowcount

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
                        INSERT INTO candidates(id, name, birthyear)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(id) DO NOTHING
                        """,
                        (
                            plan["target_candidate_id"],
                            plan["new_candidate_name"],
                            plan["new_candidate_birthyear"],
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
        operation_id = int(row["id"])
        _clog.info(
            "IDENTITY_FIX operation_id=%d issue_id=%d action=%s source_candidate=%s target_candidate=%s moved_records=%s",
            operation_id, issue_id, action, source_candidate_id, plan["target_candidate_id"],
            plan["moved_source_record_ids"],
        )
        return operation_id

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
                    "birthyear": row["birthyear"],
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
                "birthyear": payload.get("birthyear"),
                "name": payload.get("name"),
            }
            grouped[cid]["elections"].append(election)
        return list(grouped.values())

    def _get_identity_issue(self, issue_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                SELECT i.*, c.name, c.birthyear
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
                    c.id, c.name, c.birthyear,
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
                return {"id": row["id"], "name": row["name"], "birthyear": row["birthyear"], "elections": []}
            return self._group_committed_candidate_rows(real_rows)[0]
        finally:
            if close_conn:
                ctx.__exit__(None, None, None)

    def _nearby_candidates(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        birthyear = candidate.get("birthyear")
        if birthyear is None:
            return []
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT id
                FROM candidates
                WHERE name = %s
                  AND id <> %s
                  AND birthyear IS NOT NULL
                  AND ABS(birthyear - %s) = 1
                ORDER BY id
                """,
                (candidate["name"], candidate["id"], birthyear),
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
        new_candidate_birthyear = source["birthyear"]

        if action == "target_existing":
            if not target_candidate_id:
                return {"error": "請選擇要合併到哪一個候選人"}
            target = self._get_committed_candidate(target_candidate_id)
            if target is None or target["id"] == source["id"]:
                return {"error": "合併目標無效"}
            moved = selected
        elif action == "selected_new":
            target_candidate_id = self._next_available_candidate_id(source["id"])
            target = {"id": target_candidate_id, "name": source["name"], "birthyear": source["birthyear"], "elections": []}
            create_candidate = True
            moved = selected
        elif action == "others_new":
            moved = [sid for sid in source_ids if sid not in selected]
            if not moved:
                return {"error": "沒有其他 elections 可以拆出"}
            target_candidate_id = self._next_available_candidate_id(source["id"])
            target = {"id": target_candidate_id, "name": source["name"], "birthyear": source["birthyear"], "elections": []}
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
            "new_candidate_birthyear": new_candidate_birthyear,
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
                        INSERT INTO candidates(id, name, birthyear)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(id) DO NOTHING
                        """,
                        (candidate_id, _normalize_candidate_name(payload["name"]), payload.get("birthyear")),
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

        _clog.info("COMMIT_ELECTION election_id=%s auto=%d manual=%d total=%d", election_id, auto, manual, auto + manual)
        for src_id, decision in decisions.items():
            if decision["mode"] in ("manual", "manual_new"):
                payload = source_records_map[src_id]
                _clog.info(
                    "COMMIT_MANUAL election_id=%s candidate_id=%s name=%s mode=%s source_record_id=%s",
                    election_id, decision["candidate_id"], payload.get("name", ""), decision["mode"], src_id,
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

    def reset_election_data(self, election_id: str) -> dict[str, int]:
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                stats = {
                    "source_records": conn.execute(
                        "SELECT count(*) AS n FROM source_records WHERE election_id = %s",
                        (election_id,),
                    ).fetchone()["n"],
                    "resolutions": conn.execute(
                        "SELECT count(*) AS n FROM resolutions WHERE election_id = %s",
                        (election_id,),
                    ).fetchone()["n"],
                    "review_decisions": conn.execute(
                        "SELECT count(*) AS n FROM review_decisions WHERE election_id = %s",
                        (election_id,),
                    ).fetchone()["n"],
                }
                affected_rows = conn.execute(
                    """
                    SELECT DISTINCT candidate_id
                    FROM resolutions
                    WHERE election_id = %s
                      AND candidate_id IS NOT NULL
                    """,
                    (election_id,),
                ).fetchall()
                affected_candidate_ids = [row["candidate_id"] for row in affected_rows]

                conn.execute("DELETE FROM elections WHERE election_id = %s", (election_id,))

                removed_candidates = 0
                for candidate_id in affected_candidate_ids:
                    has_remaining = conn.execute(
                        "SELECT 1 FROM resolutions WHERE candidate_id = %s LIMIT 1",
                        (candidate_id,),
                    ).fetchone()
                    if has_remaining:
                        self._sync_candidate_elections(conn, [candidate_id])
                    else:
                        removed_candidates += conn.execute(
                            "DELETE FROM candidates WHERE id = %s",
                            (candidate_id,),
                        ).rowcount

        result = {
            "source_records": int(stats["source_records"]),
            "resolutions": int(stats["resolutions"]),
            "review_decisions": int(stats["review_decisions"]),
            "candidates": int(removed_candidates),
        }
        _clog.info(
            "RESET_ELECTION election_id=%s candidates_deleted=%d candidates_updated=%d",
            election_id, removed_candidates, len(affected_candidate_ids) - removed_candidates,
        )
        return result

    def delete_election(self, election_id: str) -> None:
        self.reset_election_data(election_id)

    # ------------------------------------------------------------------
    # guide_* tables
    # ------------------------------------------------------------------

    _GUIDE_FIELD_ORDER = ["姓名", "出生年月日", "性別", "學歷", "經歷"]

    def guide_tree(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT id, label, year, session, type
                FROM guide_elections
                ORDER BY type, year DESC NULLS LAST
                """
            ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            t = row["type"]
            if t not in grouped:
                grouped[t] = {"type": t, "elections": []}
            grouped[t]["elections"].append(
                {"id": row["id"], "label": row["label"], "year": row["year"], "session": row["session"]}
            )
        return list(grouped.values())

    def guide_candidates_of(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT
                    gc.id,
                    gc.ticket,
                    gc.role,
                    gc.party,
                    gc.photo_flagged,
                    gc.order_id,
                    gf_name.value AS name,
                    (gc.photo_flagged OR COALESCE(
                        (SELECT bool_or(gf.flagged) FROM guide_fields gf WHERE gf.guide_candidate_id = gc.id),
                        false
                    )) AS any_flag
                FROM guide_candidates gc
                LEFT JOIN guide_fields gf_name
                    ON gf_name.guide_candidate_id = gc.id AND gf_name.field_name = '姓名'
                WHERE gc.guide_election_id = %s
                ORDER BY gc.order_id
                """,
                (election_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def guide_election_exists(self, election_id: str) -> bool:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT 1 FROM guide_elections WHERE id = %s", (election_id,)
            ).fetchone()
        return row is not None

    def guide_delete_election(self, election_id: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute("DELETE FROM guide_elections WHERE id = %s", (election_id,))

    def guide_upsert_election(
        self,
        *,
        election_id: str,
        election_type: str,
        year: int,
        session: int | None,
        label: str,
        source_pdf_path: str,
    ) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO guide_elections(id, type, year, session, label, source_pdf_path)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (election_id, election_type, year, session, label, source_pdf_path),
            )

    def guide_insert_candidate(
        self,
        *,
        guide_election_id: str,
        ticket: int | None,
        role: str,
        party: str | None,
        photo_path: str | None,
        source_page: int | None,
        order_id: int,
    ) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_candidates
                    (guide_election_id, ticket, role, party, photo_path, source_page, order_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (guide_election_id, ticket, role, party, photo_path, source_page, order_id),
            ).fetchone()
        return row["id"]

    def guide_insert_field(
        self,
        *,
        guide_candidate_id: int,
        field_name: str,
        value: str | None,
        grade: str | None,
        source_crop_path: str | None,
        update_source: str = "parse",
    ) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO guide_fields
                    (guide_candidate_id, field_name, value, grade, source_crop_path, update_source)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (guide_candidate_id, field_name, value, grade, source_crop_path, update_source),
            )

    def guide_get_fields(self, guide_candidate_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT field_name, value, grade, source_crop_path, flagged, flag_note
                FROM guide_fields
                WHERE guide_candidate_id = %s
                ORDER BY id
                """,
                (guide_candidate_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def guide_create_snapshot(
        self,
        *,
        guide_candidate_id: int,
        version_no: int = 1,
        note: str | None = None,
    ) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_snapshots(guide_candidate_id, version_no, note)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (guide_candidate_id, version_no, note),
            ).fetchone()
        return row["id"]

    def guide_insert_snapshot_field(
        self,
        *,
        snapshot_id: int,
        field_name: str,
        value: str | None,
        grade: str | None,
        source_crop_path: str | None,
        flagged: bool = False,
        flag_note: str | None = None,
    ) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO guide_snapshot_fields
                    (snapshot_id, field_name, value, grade, source_crop_path, flagged, flag_note)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (snapshot_id, field_name, value, grade, source_crop_path, flagged, flag_note),
            )

    def guide_candidate_view(self, candidate_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            self._setup_conn(conn)

            # Candidate meta + election label
            cand_row = conn.execute(
                """
                SELECT
                    gc.id, gc.ticket, gc.role, gc.party,
                    gc.photo_path, gc.photo_flagged, gc.photo_note,
                    gc.source_page, gc.guide_election_id AS election_id,
                    ge.label AS election_label
                FROM guide_candidates gc
                JOIN guide_elections ge ON ge.id = gc.guide_election_id
                WHERE gc.id = %s
                """,
                (candidate_id,),
            ).fetchone()

            # Fields in stable order
            field_rows = conn.execute(
                """
                SELECT id, field_name, value, grade, source_crop_path, flagged, flag_note
                FROM guide_fields
                WHERE guide_candidate_id = %s
                ORDER BY array_position(
                    ARRAY['姓名','出生年月日','性別','學歷','經歷'],
                    field_name::text
                )
                """,
                (candidate_id,),
            ).fetchall()

            # Latest snapshot
            latest_snap = conn.execute(
                """
                SELECT id, version_no
                FROM guide_snapshots
                WHERE guide_candidate_id = %s
                ORDER BY version_no DESC
                LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()

            has_uncommitted = False
            if latest_snap:
                snap_field_rows = conn.execute(
                    """
                    SELECT field_name, value, flagged, flag_note
                    FROM guide_snapshot_fields
                    WHERE snapshot_id = %s
                    """,
                    (latest_snap["id"],),
                ).fetchall()
                snap_map = {r["field_name"]: dict(r) for r in snap_field_rows}
                current_field_names = {r["field_name"] for r in field_rows}
                if current_field_names != set(snap_map.keys()):
                    has_uncommitted = True
                else:
                    for fr in field_rows:
                        sn = snap_map.get(fr["field_name"])
                        if sn is None:
                            has_uncommitted = True
                            break
                        if (fr["value"] != sn["value"]
                                or fr["flagged"] != sn["flagged"]
                                or fr["flag_note"] != sn["flag_note"]):
                            has_uncommitted = True
                            break

        cand_meta = dict(cand_row)
        gender_row = next((r for r in field_rows if r["field_name"] == "性別"), None)
        cand_meta["gender"] = gender_row["value"] if gender_row else None

        fields = []
        for fr in field_rows:
            d = dict(fr)
            d["can_ai_repair"] = d["source_crop_path"] is not None
            fields.append(d)

        return {
            "candidate": cand_meta,
            "fields": fields,
            "has_uncommitted": has_uncommitted,
            "latest_version": latest_snap["version_no"] if latest_snap else 0,
        }

    def guide_snapshot_view(self, candidate_id: int, version_no: int) -> dict[str, Any]:
        with self.connect() as conn:
            self._setup_conn(conn)
            snap_row = conn.execute(
                "SELECT id FROM guide_snapshots WHERE guide_candidate_id = %s AND version_no = %s",
                (candidate_id, version_no),
            ).fetchone()
            field_rows = conn.execute(
                """
                SELECT field_name, value, grade, source_crop_path, flagged, flag_note
                FROM guide_snapshot_fields
                WHERE snapshot_id = %s
                ORDER BY array_position(
                    ARRAY['姓名','出生年月日','性別','學歷','經歷'],
                    field_name::text
                )
                """,
                (snap_row["id"],),
            ).fetchall()
            bounds = conn.execute(
                "SELECT MIN(version_no) AS min_v, MAX(version_no) AS max_v FROM guide_snapshots WHERE guide_candidate_id = %s",
                (candidate_id,),
            ).fetchone()
        return {
            "fields": [dict(r) for r in field_rows],
            "version_no": version_no,
            "min_version": bounds["min_v"],
            "max_version": bounds["max_v"],
        }

    def guide_commit(self, candidate_id: int, note: str | None = None) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                max_row = conn.execute(
                    "SELECT COALESCE(MAX(version_no), 0) AS max_v FROM guide_snapshots WHERE guide_candidate_id = %s",
                    (candidate_id,),
                ).fetchone()
                new_version = max_row["max_v"] + 1
                snap_row = conn.execute(
                    "INSERT INTO guide_snapshots(guide_candidate_id, version_no, note) VALUES (%s, %s, %s) RETURNING id",
                    (candidate_id, new_version, note),
                ).fetchone()
                snap_id = snap_row["id"]
                field_rows = conn.execute(
                    "SELECT field_name, value, grade, source_crop_path, flagged, flag_note FROM guide_fields WHERE guide_candidate_id = %s",
                    (candidate_id,),
                ).fetchall()
                for fr in field_rows:
                    conn.execute(
                        """
                        INSERT INTO guide_snapshot_fields
                            (snapshot_id, field_name, value, grade, source_crop_path, flagged, flag_note)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (snap_id, fr["field_name"], fr["value"], fr["grade"],
                         fr["source_crop_path"], fr["flagged"], fr["flag_note"]),
                    )
        return new_version

    def guide_discard(self, candidate_id: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                latest_snap = conn.execute(
                    """
                    SELECT id FROM guide_snapshots
                    WHERE guide_candidate_id = %s
                    ORDER BY version_no DESC
                    LIMIT 1
                    """,
                    (candidate_id,),
                ).fetchone()
                if latest_snap is None:
                    return
                snap_fields = conn.execute(
                    """
                    SELECT field_name, value, grade, source_crop_path, flagged, flag_note
                    FROM guide_snapshot_fields
                    WHERE snapshot_id = %s
                    """,
                    (latest_snap["id"],),
                ).fetchall()
                for sf in snap_fields:
                    conn.execute(
                        """
                        UPDATE guide_fields
                        SET value = %s, grade = %s, source_crop_path = %s,
                            flagged = %s, flag_note = %s, updated_at = current_timestamp
                        WHERE guide_candidate_id = %s AND field_name = %s
                        """,
                        (sf["value"], sf["grade"], sf["source_crop_path"],
                         sf["flagged"], sf["flag_note"], candidate_id, sf["field_name"]),
                    )

    def guide_set_field_value(self, field_id: int, value: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                UPDATE guide_fields
                SET value = %s, update_source = 'manual', grade = NULL, updated_at = current_timestamp
                WHERE id = %s
                """,
                (value, field_id),
            )

    def guide_flag_field(self, field_id: int, note: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE guide_fields SET flagged = true, flag_note = %s WHERE id = %s",
                (note, field_id),
            )

    def guide_unflag_field(self, field_id: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE guide_fields SET flagged = false, flag_note = NULL WHERE id = %s",
                (field_id,),
            )

    def guide_flag_photo(self, candidate_id: int, note: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE guide_candidates SET photo_flagged = true, photo_note = %s WHERE id = %s",
                (note, candidate_id),
            )

    def guide_unflag_photo(self, candidate_id: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE guide_candidates SET photo_flagged = false, photo_note = NULL WHERE id = %s",
                (candidate_id,),
            )

    # --- 文字欄 AI 修復工作 (Phase 6) ---

    def guide_get_field(self, candidate_id: int, field_name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT id, value, source_crop_path, flagged FROM guide_fields "
                "WHERE guide_candidate_id = %s AND field_name = %s",
                (candidate_id, field_name),
            ).fetchone()
        return dict(row) if row else None

    def guide_apply_ai_value(self, field_id: int, value: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                UPDATE guide_fields
                SET value = %s, update_source = 'ai', grade = NULL, updated_at = current_timestamp
                WHERE id = %s
                """,
                (value, field_id),
            )

    def guide_create_repair_job(self, candidate_id: int, target: str,
                                user_note: str | None = None) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_repair_jobs(guide_candidate_id, target, status, user_note)
                VALUES (%s, %s, 'queued', %s)
                RETURNING id
                """,
                (candidate_id, target, user_note),
            ).fetchone()
        return row["id"]

    def guide_get_repair_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT * FROM guide_repair_jobs WHERE id = %s", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def guide_set_repair_running(self, job_id: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE guide_repair_jobs SET status = 'running' WHERE id = %s",
                (job_id,),
            )

    def guide_finish_repair_job(self, job_id: int, *, status: str,
                                before_value: str | None = None,
                                result_value: str | None = None,
                                error: str | None = None) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                UPDATE guide_repair_jobs
                SET status = %s, before_value = %s, result_value = %s, error = %s,
                    finished_at = current_timestamp
                WHERE id = %s
                """,
                (status, before_value, result_value, error, job_id),
            )

    def delete_candidate(self, candidate_id: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute("DELETE FROM candidates WHERE id = %s", (candidate_id,))
        _clog.info("DELETE_CANDIDATE candidate_id=%s", candidate_id)

    def rename_candidate(self, old_id: str, new_id: str, new_birthyear: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            if conn.execute("SELECT 1 FROM candidates WHERE id = %s", (new_id,)).fetchone():
                raise ValueError(f"候選人 {new_id} 已存在，id rename 失敗，需人工處理")
            with conn.transaction():
                conn.execute(
                    "INSERT INTO candidates(id, name, birthyear, alias_names) SELECT %s, name, %s, alias_names FROM candidates WHERE id = %s",
                    (new_id, new_birthyear, old_id),
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
        _clog.info("RENAME_CANDIDATE old_id=%s new_id=%s birthyear=%s", old_id, new_id, new_birthyear)
