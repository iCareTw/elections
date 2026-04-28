from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
from psycopg import OperationalError
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.normalize import normalize_name as _normalize_name

ROOT = Path(__file__).resolve().parents[2]


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

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        if not self.config.database_url:
            raise ValueError("PostgreSQL connection is not configured")

        try:
            conn = psycopg.connect(self.config.database_url, row_factory=dict_row)
        except OperationalError:
            raise ConnectionError("Could not connect to PostgreSQL") from None
        if not self._schema_exists(conn):
            conn.close()
            raise ConnectionError(f"PostgreSQL schema is not available: {self.config.schema}")
        conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(self.config.schema)))
        return conn

    def _schema_exists(self, conn: psycopg.Connection[dict[str, Any]]) -> bool:
        row = conn.execute(
            "select 1 from pg_namespace where nspname = %s",
            (self.config.schema,),
        ).fetchone()
        return row is not None

    def validate_connection(self) -> None:
        with self.connect() as conn:
            conn.execute("select 1").fetchone()

    def init_schema(self) -> None:
        sql_path = ROOT / "db" / "001_init.sql"
        ddl = sql_path.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.execute(ddl)

    def upsert_election(self, election: dict[str, Any]) -> None:
        with self.connect() as conn:
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

    def save_resolution(
        self,
        *,
        election_id: str,
        source_record_id: str,
        candidate_id: str | None,
        mode: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into resolutions(source_record_id, election_id, candidate_id, mode)
                values (%s, %s, %s, %s)
                on conflict(source_record_id) do update set
                    election_id = excluded.election_id,
                    candidate_id = excluded.candidate_id,
                    mode = excluded.mode
                """,
                (source_record_id, election_id, candidate_id, mode),
            )

    def get_resolution(self, source_record_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return conn.execute(
                "select * from resolutions where source_record_id = %s",
                (source_record_id,),
            ).fetchone()

    def list_elections(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select
                    e.election_id,
                    e.type,
                    e.label,
                    e.path,
                    e.year,
                    e.session,
                    case
                        when count(sr.source_record_id) = 0 then 'todo'
                        when count(sr.source_record_id) filter (where r.source_record_id is null) > 0 then 'review'
                        else 'done'
                    end as status,
                    count(sr.source_record_id)::int as imported_count,
                    count(sr.source_record_id) filter (where r.source_record_id is null)::int as unresolved_count,
                    count(r.source_record_id)::int as resolved_count
                from elections e
                left join source_records sr on sr.election_id = e.election_id
                left join resolutions r on r.source_record_id = sr.source_record_id
                group by e.election_id, e.type, e.label, e.path, e.year, e.session
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
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_records(source_record_id, election_id, name, birthday, payload)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(source_record_id) DO UPDATE SET
                    election_id = EXCLUDED.election_id,
                    name        = EXCLUDED.name,
                    birthday    = EXCLUDED.birthday,
                    payload     = EXCLUDED.payload
                """,
                (
                    source_record_id,
                    election_id,
                    payload["name"],
                    payload.get("birthday"),
                    Jsonb(payload),
                ),
            )

    def get_source_record(self, source_record_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT source_record_id, election_id, name, birthday, payload FROM source_records WHERE source_record_id = %s",
                (source_record_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_source_records(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT source_record_id, election_id, name, birthday, payload
                FROM source_records
                WHERE election_id = %s
                ORDER BY source_record_id
                """,
                (election_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_candidate(self, id: str, name: str, birthday: int | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO candidates(id, name, birthday)
                VALUES (%s, %s, %s)
                ON CONFLICT(id) DO NOTHING
                """,
                (id, _normalize_name(name), birthday),
            )

    def list_candidates_by_name(self, name: str) -> list[dict[str, Any]]:
        normalized = _normalize_name(name)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, birthday FROM candidates WHERE name = %s",
                (normalized,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_candidates_with_elections(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
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
                    (candidate_id, _normalize_name(payload["name"]), payload.get("birthday")),
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

        return auto, manual

    def delete_election(self, election_id: str) -> None:
        with self.connect() as conn:
            conn.execute("delete from elections where election_id = %s", (election_id,))

    def delete_candidate(self, candidate_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM candidates WHERE id = %s", (candidate_id,))
