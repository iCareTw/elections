from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
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

# ---------------------------------------------------------------- 公報左樹
#
# 每場選舉自己帶一條 nav_path(見 election_meta),左樹照它攤開成資料夾。

_NAV_TYPE_LABELS = {"president": "總統", "mayor": "縣市長", "legislator": "立法委員"}
_NAV_TOP_ORDER = ("總統", "縣市長", "立法委員")
# 年份/屆次那層由新到舊,其餘由小到大
_NAV_YEARISH = re.compile(r"^(第\d+[任屆]\s*)?\d{3,4}$")


def _nav_node(label: str) -> dict[str, Any]:
    return {"label": label, "id": None, "children": [], "pending_commit_count": 0}


def _nav_path_of(row: Any) -> list[str]:
    """選舉在左樹的位置。舊資料沒填 nav_path 時,退回用類型/年份/地區拼。"""
    raw = row["nav_path"]
    if raw:
        return [seg for seg in raw.split("/") if seg]
    top = _NAV_TYPE_LABELS.get(row["type"], row["type"])
    if row["region"]:
        return [top, str(row["year"]), row["region"]]
    return [top, row["label"] or str(row["year"])]


def _nav_key(label: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", label)]


def _nav_fill(node: dict[str, Any], pending: dict[str, int]) -> int:
    """排序子節點並把未提交組數往上累加,回傳本節點的總數。"""
    kids = node["children"]
    if kids:
        newest_first = all(_NAV_YEARISH.match(k["label"]) for k in kids)
        kids.sort(key=lambda k: _nav_key(k["label"]), reverse=newest_first)
    if not node["label"]:                       # 根:類型依固定順序
        kids.sort(key=lambda k: (_NAV_TOP_ORDER.index(k["label"])
                                 if k["label"] in _NAV_TOP_ORDER else len(_NAV_TOP_ORDER)))
    total = pending.get(node["id"], 0) if node["id"] else 0
    for kid in kids:
        total += _nav_fill(kid, pending)
    node["pending_commit_count"] = total
    return total


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


# 紅點:AI 判讀文字與截圖不一致(仍為解析原值、尚未人工/AI 編輯過)時提示複核。
# 乾淨分級對齊 verify.py 的 OK 集合(含「看圖存疑」= 幾何為準欄位看圖不同但已採幾何值,不標紅)。
_GUIDE_CLEAN_GRADES = {"完全一致", "幾乎一致", "看圖存疑", "不適用"}


def _guide_has_concern(grade, update_source) -> bool:
    if update_source and update_source != "parse":   # 已編輯 → 視為已確認,紅點消失
        return False
    return bool(grade) and grade not in _GUIDE_CLEAN_GRADES


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
            # 公報匯入一份要跑幾十分鐘到幾小時,連線在池子裡閒置到被 server 關掉,
            # 回頭要寫 DB 時才發現斷線 → 借出前先驗一次,壞的換一條新的。
            check=ConnectionPool.check_connection,
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
        ddl_files = ("001_init.sql", "004_rename_birthday_to_birthyear.sql",
                     "005_voter_guide.sql", "006_voter_guide_groups.sql",
                     "007_guide_manual_photos.sql", "008_guide_import_jobs.sql",
                     "009_guide_election_region.sql",
                     "010_guide_election_nav_path.sql")
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
        """左樹:照每場選舉自己的 nav_path 攤成資料夾。

        總統只有兩層(總統/第16任 2024),立委有五層(立法委員/第11屆 2024/區域/
        臺北市/第1選舉區),所以這裡不預設層數,節點一律 {label, id, children}:
        有 id 的是可點的選舉,其餘是資料夾。未提交組數往上層累加。
        """
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT id, label, year, session, type, region, nav_path
                FROM guide_elections
                ORDER BY type, year DESC NULLS LAST, region NULLS FIRST, id
                """
            ).fetchall()
            # 每場選舉未 commit 的組數(供左樹提醒記號)
            pending: dict[str, int] = {}
            for gr in conn.execute(
                "SELECT id, guide_election_id FROM guide_groups"
            ).fetchall():
                if self._group_has_uncommitted(conn, gr["id"]):
                    eid = gr["guide_election_id"]
                    pending[eid] = pending.get(eid, 0) + 1

        root: dict[str, Any] = _nav_node("")
        for row in rows:
            path = _nav_path_of(row)
            node = root
            for name in path[:-1]:
                child = next((c for c in node["children"] if c["label"] == name
                              and not c["id"]), None)
                if child is None:
                    child = _nav_node(name)
                    node["children"].append(child)
                node = child
            leaf = _nav_node(path[-1])
            leaf["id"] = row["id"]
            node["children"].append(leaf)
        _nav_fill(root, pending)
        return root["children"]

    def guide_candidates_of(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT
                    gc.id,
                    g.ticket,
                    gc.role,
                    g.party,
                    gc.guide_group_id,
                    gc.order_id,
                    gf_name.value AS name
                FROM guide_candidates gc
                JOIN guide_groups g ON g.id = gc.guide_group_id
                LEFT JOIN guide_fields gf_name
                    ON gf_name.guide_candidate_id = gc.id AND gf_name.field_name = '姓名'
                WHERE gc.guide_election_id = %s
                ORDER BY gc.order_id
                """,
                (election_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def guide_imported_pdf_map(self) -> dict[str, str]:
        """已匯入公報:來源 PDF 絕對路徑 → guide_elections.id(供匯入清單標記與連往校對台)。"""
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                "SELECT id, source_pdf_path FROM guide_elections "
                "WHERE source_pdf_path IS NOT NULL"
            ).fetchall()
        out = {}
        for r in rows:
            try:
                out[str(Path(r["source_pdf_path"]).resolve())] = r["id"]
            except Exception:
                out[r["source_pdf_path"]] = r["id"]
        return out

    def guide_election_row(self, election_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT * FROM guide_elections WHERE id = %s", (election_id,)
            ).fetchone()
        return dict(row) if row else None

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
        region: str | None = None,
        nav_path: str | None = None,
    ) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO guide_elections
                    (id, type, year, session, label, region, source_pdf_path, nav_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (election_id, election_type, year, session, label, region,
                 source_pdf_path, nav_path),
            )

    def guide_add_manual_group(self, election_id: str, roles: tuple[str, ...]) -> int:
        """人工補一組候選人(公報解析不出來時),欄位留空待填。回傳 group id。

        號次接在現有的後面。建出來的結構與解析匯入完全一樣(含 v1 snapshot),
        所以後續編輯、提交、AI 修復都走同一條路。
        """
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT COALESCE(MAX(ticket), 0) t, COALESCE(MAX(order_id), 0) o "
                "FROM guide_groups WHERE guide_election_id = %s",
                (election_id,),
            ).fetchone()
        ticket, order_id = row["t"] + 1, row["o"] + 1

        group_id = self.guide_insert_group(
            guide_election_id=election_id, ticket=ticket, party=None, order_id=order_id)
        self.guide_upsert_platform(guide_group_id=group_id, value=None, grade=None,
                                   source_crop_path=None, update_source="manual")
        for role in (roles or ("第1名",)):
            order_id += 1
            candidate_id = self.guide_insert_candidate(
                guide_election_id=election_id, guide_group_id=group_id, role=role,
                photo_path=None, source_page=None, order_id=order_id)
            for field in self._GUIDE_FIELD_ORDER:
                self.guide_insert_field(
                    guide_candidate_id=candidate_id, field_name=field, value=None,
                    grade=None, source_crop_path=None, update_source="manual")
        snapshot_id = self.guide_create_group_snapshot(guide_group_id=group_id,
                                                      version_no=1)
        for cand in self.guide_candidates_of(election_id):
            if cand["guide_group_id"] != group_id:
                continue
            for f in self.guide_get_fields(cand["id"]):
                self.guide_insert_group_snapshot_field(
                    snapshot_id=snapshot_id, scope=cand["role"],
                    field_name=f["field_name"], value=f["value"], grade=f["grade"],
                    source_crop_path=f["source_crop_path"],
                    flagged=f["flagged"], flag_note=f["flag_note"])
        return group_id

    def guide_insert_group(
        self,
        *,
        guide_election_id: str,
        ticket: int | None,
        party: str | None,
        order_id: int,
    ) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_groups(guide_election_id, ticket, party, order_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (guide_election_id, ticket, party, order_id),
            ).fetchone()
        return row["id"]

    def guide_insert_candidate(
        self,
        *,
        guide_election_id: str,
        guide_group_id: int,
        role: str,
        photo_path: str | None,
        source_page: int | None,
        order_id: int,
    ) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_candidates
                    (guide_election_id, guide_group_id, role, photo_path, source_page, order_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (guide_election_id, guide_group_id, role, photo_path, source_page, order_id),
            ).fetchone()
        return row["id"]

    def guide_upsert_platform(
        self,
        *,
        guide_group_id: int,
        value: str | None,
        grade: str | None,
        source_crop_path: str | None,
        update_source: str = "parse",
    ) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO guide_group_platform
                    (guide_group_id, value, grade, source_crop_path, update_source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (guide_group_id) DO UPDATE SET
                    value = EXCLUDED.value, grade = EXCLUDED.grade,
                    source_crop_path = EXCLUDED.source_crop_path,
                    update_source = EXCLUDED.update_source, updated_at = current_timestamp
                """,
                (guide_group_id, value, grade, source_crop_path, update_source),
            )

    def guide_get_platform(self, guide_group_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                SELECT id, guide_group_id, value, grade, source_crop_path,
                       flagged, flag_note, update_source
                FROM guide_group_platform WHERE guide_group_id = %s
                """,
                (guide_group_id,),
            ).fetchone()
        return dict(row) if row else None

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

    def guide_create_group_snapshot(
        self,
        *,
        guide_group_id: int,
        version_no: int = 1,
        note: str | None = None,
    ) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_group_snapshots(guide_group_id, version_no, note)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (guide_group_id, version_no, note),
            ).fetchone()
        return row["id"]

    def guide_insert_group_snapshot_field(
        self,
        *,
        snapshot_id: int,
        scope: str,
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
                INSERT INTO guide_group_snapshot_fields
                    (snapshot_id, scope, field_name, value, grade, source_crop_path, flagged, flag_note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (snapshot_id, scope, field_name, value, grade, source_crop_path, flagged, flag_note),
            )

    _FIELD_ORDER_SQL = ("array_position(ARRAY['姓名','出生年月日','性別','學歷','經歷'], "
                        "field_name::text)")

    def _guide_candidate_block(self, conn, candidate_id: int) -> dict[str, Any]:
        cand = conn.execute(
            """
            SELECT gc.id, gc.role, gc.photo_path, gc.photo_flagged,
                   gc.photo_note, gc.source_page
            FROM guide_candidates gc WHERE gc.id = %s
            """,
            (candidate_id,),
        ).fetchone()
        field_rows = conn.execute(
            f"""
            SELECT id, field_name, value, grade, source_crop_path, flagged, flag_note, update_source
            FROM guide_fields WHERE guide_candidate_id = %s
            ORDER BY {self._FIELD_ORDER_SQL}
            """,
            (candidate_id,),
        ).fetchall()
        meta = dict(cand)
        gender = next((r["value"] for r in field_rows if r["field_name"] == "性別"), None)
        meta["gender"] = gender
        fields = []
        for fr in field_rows:
            d = dict(fr)
            d["can_ai_repair"] = d["source_crop_path"] is not None
            d["concern"] = _guide_has_concern(d.get("grade"), d.get("update_source"))
            fields.append(d)
        return {"candidate": meta, "fields": fields}

    def _guide_group_current_state(self, conn, group_id: int) -> dict[tuple[str, str], dict]:
        """組目前狀態:{(scope, field_name): {value, flagged, flag_note}}。scope=角色 或 政見。"""
        state: dict[tuple[str, str], dict] = {}
        rows = conn.execute(
            """
            SELECT gc.role AS scope, gf.field_name, gf.value, gf.flagged, gf.flag_note
            FROM guide_fields gf JOIN guide_candidates gc ON gc.id = gf.guide_candidate_id
            WHERE gc.guide_group_id = %s
            """,
            (group_id,),
        ).fetchall()
        for r in rows:
            state[(r["scope"], r["field_name"])] = {
                "value": r["value"], "flagged": r["flagged"], "flag_note": r["flag_note"]}
        plat = conn.execute(
            "SELECT value, flagged, flag_note FROM guide_group_platform WHERE guide_group_id = %s",
            (group_id,),
        ).fetchone()
        if plat is not None:
            state[("政見", "政見")] = {
                "value": plat["value"], "flagged": plat["flagged"], "flag_note": plat["flag_note"]}
        return state

    def _group_has_uncommitted(self, conn, group_id: int) -> bool:
        """組目前狀態是否與最新快照不同(未提交變更)。無快照視為無變更。"""
        latest = conn.execute(
            "SELECT id FROM guide_group_snapshots WHERE guide_group_id = %s "
            "ORDER BY version_no DESC LIMIT 1",
            (group_id,),
        ).fetchone()
        if not latest:
            return False
        snap = {(r["scope"], r["field_name"]): r for r in conn.execute(
            "SELECT scope, field_name, value, flagged, flag_note "
            "FROM guide_group_snapshot_fields WHERE snapshot_id = %s",
            (latest["id"],),
        ).fetchall()}
        cur = self._guide_group_current_state(conn, group_id)
        if set(cur.keys()) != set(snap.keys()):
            return True
        for k, c in cur.items():
            s = snap[k]
            if (c["value"] != s["value"] or c["flagged"] != s["flagged"]
                    or c["flag_note"] != s["flag_note"]):
                return True
        return False

    def guide_group_view(self, election_id: str, ticket: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            grp = conn.execute(
                """
                SELECT g.id, g.ticket, g.party, g.guide_election_id AS election_id,
                       ge.label AS election_label, ge.type AS election_type
                FROM guide_groups g JOIN guide_elections ge ON ge.id = g.guide_election_id
                WHERE g.guide_election_id = %s AND g.ticket = %s
                """,
                (election_id, ticket),
            ).fetchone()
            if grp is None:
                return None
            group_id = grp["id"]

            cand_rows = conn.execute(
                "SELECT id, role FROM guide_candidates WHERE guide_group_id = %s "
                "ORDER BY order_id", (group_id,)
            ).fetchall()
            members = [self._guide_candidate_block(conn, r["id"]) for r in cand_rows]

            plat_row = conn.execute(
                """
                SELECT id, value, grade, source_crop_path, flagged, flag_note, update_source
                FROM guide_group_platform WHERE guide_group_id = %s
                """,
                (group_id,),
            ).fetchone()
            platform = dict(plat_row) if plat_row else {
                "id": None, "value": None, "grade": None, "source_crop_path": None,
                "flagged": False, "flag_note": None, "update_source": None}
            platform["can_ai_repair"] = bool(platform.get("source_crop_path"))
            platform["concern"] = _guide_has_concern(platform.get("grade"),
                                                     platform.get("update_source"))

            latest = conn.execute(
                "SELECT id, version_no FROM guide_group_snapshots WHERE guide_group_id = %s "
                "ORDER BY version_no DESC LIMIT 1",
                (group_id,),
            ).fetchone()

            has_uncommitted = self._group_has_uncommitted(conn, group_id)

        return {
            "group": {"id": group_id, "ticket": grp["ticket"], "party": grp["party"],
                      "election_id": grp["election_id"],
                      "election_label": grp["election_label"],
                      "election_type": grp["election_type"],
                      "ticket_label": "組" if len(members) > 1 else "號"},
            "members": members,
            "platform": platform,
            "has_uncommitted": has_uncommitted,
            "latest_version": latest["version_no"] if latest else 0,
        }

    def guide_group_snapshot_view(self, group_id: int, version_no: int) -> dict[str, Any]:
        with self.connect() as conn:
            self._setup_conn(conn)
            snap = conn.execute(
                "SELECT id FROM guide_group_snapshots WHERE guide_group_id = %s AND version_no = %s",
                (group_id, version_no),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT scope, field_name, value, grade, source_crop_path, flagged, flag_note
                FROM guide_group_snapshot_fields WHERE snapshot_id = %s
                ORDER BY CASE scope WHEN '總統' THEN 0 WHEN '副總統' THEN 1
                                    WHEN '政見' THEN 9 ELSE 0 END,
                         scope, {self._FIELD_ORDER_SQL}
                """,
                (snap["id"],),
            ).fetchall()
            bounds = conn.execute(
                "SELECT MIN(version_no) AS min_v, MAX(version_no) AS max_v "
                "FROM guide_group_snapshots WHERE guide_group_id = %s",
                (group_id,),
            ).fetchone()
        return {
            "fields": [dict(r) for r in rows],
            "version_no": version_no,
            "min_version": bounds["min_v"],
            "max_version": bounds["max_v"],
        }

    def guide_group_commit(self, group_id: int, note: str | None = None) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                mx = conn.execute(
                    "SELECT COALESCE(MAX(version_no),0) AS m FROM guide_group_snapshots WHERE guide_group_id = %s",
                    (group_id,),
                ).fetchone()
                new_version = mx["m"] + 1
                snap_id = conn.execute(
                    "INSERT INTO guide_group_snapshots(guide_group_id, version_no, note) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (group_id, new_version, note),
                ).fetchone()["id"]
                # 正副各欄
                rows = conn.execute(
                    """
                    SELECT gc.role AS scope, gf.field_name, gf.value, gf.grade,
                           gf.source_crop_path, gf.flagged, gf.flag_note
                    FROM guide_fields gf JOIN guide_candidates gc ON gc.id = gf.guide_candidate_id
                    WHERE gc.guide_group_id = %s
                    """,
                    (group_id,),
                ).fetchall()
                for r in rows:
                    conn.execute(
                        "INSERT INTO guide_group_snapshot_fields "
                        "(snapshot_id, scope, field_name, value, grade, source_crop_path, flagged, flag_note) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (snap_id, r["scope"], r["field_name"], r["value"], r["grade"],
                         r["source_crop_path"], r["flagged"], r["flag_note"]),
                    )
                # 政見
                plat = conn.execute(
                    "SELECT value, grade, source_crop_path, flagged, flag_note "
                    "FROM guide_group_platform WHERE guide_group_id = %s",
                    (group_id,),
                ).fetchone()
                if plat is not None:
                    conn.execute(
                        "INSERT INTO guide_group_snapshot_fields "
                        "(snapshot_id, scope, field_name, value, grade, source_crop_path, flagged, flag_note) "
                        "VALUES (%s,'政見','政見',%s,%s,%s,%s,%s)",
                        (snap_id, plat["value"], plat["grade"], plat["source_crop_path"],
                         plat["flagged"], plat["flag_note"]),
                    )
        return new_version

    def guide_group_discard(self, group_id: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            with conn.transaction():
                latest = conn.execute(
                    "SELECT id FROM guide_group_snapshots WHERE guide_group_id = %s "
                    "ORDER BY version_no DESC LIMIT 1",
                    (group_id,),
                ).fetchone()
                if latest is None:
                    return
                sfields = conn.execute(
                    "SELECT scope, field_name, value, grade, source_crop_path, flagged, flag_note "
                    "FROM guide_group_snapshot_fields WHERE snapshot_id = %s",
                    (latest["id"],),
                ).fetchall()
                for sf in sfields:
                    # 還原時把 update_source 一併回到 'parse',紅點(concern)才會依還原後的 grade 正確重算
                    if sf["scope"] == "政見":
                        conn.execute(
                            """
                            UPDATE guide_group_platform
                            SET value=%s, grade=%s, source_crop_path=%s, flagged=%s,
                                flag_note=%s, update_source='parse', updated_at=current_timestamp
                            WHERE guide_group_id = %s
                            """,
                            (sf["value"], sf["grade"], sf["source_crop_path"],
                             sf["flagged"], sf["flag_note"], group_id),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE guide_fields gf
                            SET value=%s, grade=%s, source_crop_path=%s, flagged=%s,
                                flag_note=%s, update_source='parse', updated_at=current_timestamp
                            FROM guide_candidates gc
                            WHERE gf.guide_candidate_id = gc.id
                              AND gc.guide_group_id = %s AND gc.role = %s
                              AND gf.field_name = %s
                            """,
                            (sf["value"], sf["grade"], sf["source_crop_path"],
                             sf["flagged"], sf["flag_note"], group_id, sf["scope"], sf["field_name"]),
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

    # --- 組共用政見:手動 / 修復目標 ---

    def guide_set_platform_value(self, group_id: int, value: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                UPDATE guide_group_platform
                SET value = %s, update_source = 'manual', grade = NULL, updated_at = current_timestamp
                WHERE guide_group_id = %s
                """,
                (value, group_id),
            )

    def guide_platform_ref(self, group_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT guide_group_id, value, source_crop_path FROM guide_group_platform WHERE guide_group_id = %s",
                (group_id,),
            ).fetchone()
        return dict(row) if row else None

    def guide_apply_ai_platform(self, group_id: int, value: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                UPDATE guide_group_platform
                SET value = %s, update_source = 'ai', grade = NULL, updated_at = current_timestamp
                WHERE guide_group_id = %s
                """,
                (value, group_id),
            )

    # --- 文字欄 AI 修復工作 (Phase 6) ---

    def guide_field_ref(self, field_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT guide_candidate_id, field_name, source_crop_path "
                "FROM guide_fields WHERE id = %s",
                (field_id,),
            ).fetchone()
        return dict(row) if row else None

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

    # --- 公報匯入工作 (DB 佇列,狀態可跨頁面查詢) ---

    def guide_create_import_job(self, pdf_path: str, pdf_name: str | None = None) -> int:
        """把一份公報排入匯入佇列(狀態 queued),由單一 worker 依序處理。"""
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_import_jobs(pdf_path, pdf_name, status, message)
                VALUES (%s, %s, 'queued', '排隊中')
                RETURNING id
                """,
                (pdf_path, pdf_name),
            ).fetchone()
        return row["id"]

    def guide_requeue_running_import_jobs(self) -> int:
        """把先前程序中斷遺留的 running 工作重設回 queued(啟動時復原)。回傳筆數。"""
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                "UPDATE guide_import_jobs SET status = 'queued', message = '排隊中', "
                "done = 0, total = 0, updated_at = current_timestamp "
                "WHERE status = 'running' RETURNING id"
            ).fetchall()
        return len(rows)

    def guide_has_queued_import_jobs(self) -> bool:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT 1 FROM guide_import_jobs WHERE status = 'queued' LIMIT 1"
            ).fetchone()
        return row is not None

    def guide_claim_next_import_job(self) -> dict[str, Any] | None:
        """原子取出最舊的 queued 工作並標記 running;佇列空時回傳 None。"""
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                UPDATE guide_import_jobs SET status = 'running', message = '開始解析…',
                    updated_at = current_timestamp
                WHERE id = (
                    SELECT id FROM guide_import_jobs WHERE status = 'queued'
                    ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """
            ).fetchone()
        return dict(row) if row else None

    def guide_list_import_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        """近期匯入工作(佇列 + 進行中優先,其餘依新到舊),供匯入頁佇列清單。

        每份公報只留最新一筆:重跑成功後,舊的失敗紀錄對決策已無用(詳情在 log)。
        """
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (pdf_path) * FROM guide_import_jobs
                    ORDER BY pdf_path, id DESC
                ) latest
                ORDER BY
                    CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                    CASE WHEN status IN ('queued', 'running') THEN id END ASC,
                    id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def guide_latest_import_by_path(self) -> dict[str, dict[str, Any]]:
        """每份公報最新一筆匯入工作,以絕對路徑為 key(供匯入清單標示各列狀態)。"""
        out = {}
        for j in self.guide_list_import_jobs(limit=200):
            try:
                out[str(Path(j["pdf_path"]).resolve())] = j
            except Exception:
                out[j["pdf_path"]] = j
        return out

    def guide_update_import_progress(self, job_id: int, message: str,
                                     done: int, total: int) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                UPDATE guide_import_jobs
                SET message = %s, done = %s, total = %s, updated_at = current_timestamp
                WHERE id = %s
                """,
                (message, done, total, job_id),
            )

    def guide_finish_import_job(self, job_id: int, *, status: str,
                                message: str | None = None,
                                election_id: str | None = None,
                                error: str | None = None) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                UPDATE guide_import_jobs
                SET status = %s, message = %s, election_id = %s, error = %s,
                    updated_at = current_timestamp, finished_at = current_timestamp
                WHERE id = %s
                """,
                (status, message, election_id, error, job_id),
            )

    def guide_get_import_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT * FROM guide_import_jobs WHERE id = %s", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def guide_active_import_job(self) -> dict[str, Any] | None:
        """供全站側欄常駐指示:優先顯示解析中那筆,並附佇列剩餘份數 queued_count。"""
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                SELECT * FROM guide_import_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            n = conn.execute(
                "SELECT count(*) AS c FROM guide_import_jobs WHERE status = 'queued'"
            ).fetchone()["c"]
        out = dict(row)
        out["queued_count"] = n
        return out

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

    def guide_create_platform_repair_job(self, group_id: int,
                                         user_note: str | None = None) -> int:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                INSERT INTO guide_repair_jobs(guide_group_id, target, status, user_note)
                VALUES (%s, '政見', 'queued', %s)
                RETURNING id
                """,
                (group_id, user_note),
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

    # --- 照片手動圈選補正 (Phase 7) ---

    def guide_candidate_pdf_ref(self, candidate_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                SELECT c.id, c.source_page, c.photo_path, e.source_pdf_path
                FROM guide_candidates c
                JOIN guide_elections e ON e.id = c.guide_election_id
                WHERE c.id = %s
                """,
                (candidate_id,),
            ).fetchone()
        return dict(row) if row else None

    def guide_set_photo_path(self, candidate_id: int, path: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                "UPDATE guide_candidates SET photo_path = %s WHERE id = %s",
                (path, candidate_id),
            )

    def guide_candidate_identity(self, candidate_id: int) -> dict[str, Any] | None:
        """candidate_id → {election_id, ticket, role}(手動照片的穩定鍵)。"""
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                """
                SELECT g.guide_election_id AS election_id, g.ticket, gc.role
                FROM guide_candidates gc JOIN guide_groups g ON g.id = gc.guide_group_id
                WHERE gc.id = %s
                """,
                (candidate_id,),
            ).fetchone()
        return dict(row) if row else None

    def guide_upsert_manual_photo(self, election_id: str, ticket: int, role: str,
                                  path: str) -> None:
        with self.connect() as conn:
            self._setup_conn(conn)
            conn.execute(
                """
                INSERT INTO guide_manual_photos(election_id, ticket, role, path)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (election_id, ticket, role) DO UPDATE SET
                    path = EXCLUDED.path, updated_at = current_timestamp
                """,
                (election_id, ticket, role, path),
            )

    def guide_apply_manual_photos(self, election_id: str) -> int:
        """把已登記的手動照片(檔案存在者)套回對應候選人的 photo_path。回傳套用筆數。

        供 load 完成後呼叫,確保重載/重解析後手動更正不遺失。
        """
        applied = 0
        with self.connect() as conn:
            self._setup_conn(conn)
            rows = conn.execute(
                "SELECT ticket, role, path FROM guide_manual_photos WHERE election_id = %s",
                (election_id,),
            ).fetchall()
            for r in rows:
                if not Path(r["path"]).exists():
                    continue
                conn.execute(
                    """
                    UPDATE guide_candidates gc SET photo_path = %s
                    FROM guide_groups g
                    WHERE gc.guide_group_id = g.id AND g.guide_election_id = %s
                      AND g.ticket = %s AND gc.role = %s
                    """,
                    (r["path"], election_id, r["ticket"], r["role"]),
                )
                applied += 1
        return applied

    def guide_group_locate(self, group_id: int) -> dict[str, Any] | None:
        """group_id → {election_id, ticket}(供 web 由 group_id 導到組視圖)。"""
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT guide_election_id AS election_id, ticket FROM guide_groups WHERE id = %s",
                (group_id,),
            ).fetchone()
        return dict(row) if row else None

    def guide_candidate_group_id(self, candidate_id: int) -> int | None:
        with self.connect() as conn:
            self._setup_conn(conn)
            row = conn.execute(
                "SELECT guide_group_id FROM guide_candidates WHERE id = %s", (candidate_id,)
            ).fetchone()
        return row["guide_group_id"] if row else None

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
