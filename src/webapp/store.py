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
        with self.connect() as conn:
            conn.execute(
                """
                create table if not exists elections (
                    election_id text primary key,
                    type text not null,
                    label text not null,
                    path text not null,
                    year integer,
                    session integer,
                    status text not null default 'todo',
                    updated_at timestamptz not null default current_timestamp
                )
                """
            )
            conn.execute(
                """
                create table if not exists source_records (
                    source_record_id text primary key,
                    election_id text not null references elections(election_id) on delete cascade,
                    name text not null,
                    birthday integer,
                    payload jsonb not null,
                    imported_at timestamptz not null default current_timestamp
                )
                """
            )
            conn.execute(
                """
                create table if not exists resolutions (
                    source_record_id text primary key references source_records(source_record_id) on delete cascade,
                    election_id text not null references elections(election_id) on delete cascade,
                    candidate_id text,
                    mode text not null,
                    decided_at timestamptz not null default current_timestamp
                )
                """
            )
            conn.execute(
                """
                create table if not exists operation_logs (
                    id bigserial primary key,
                    election_id text references elections(election_id) on delete set null,
                    source_record_id text,
                    action text not null,
                    payload jsonb not null default '{}'::jsonb,
                    created_at timestamptz not null default current_timestamp
                )
                """
            )

    def upsert_election(self, election: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into elections(election_id, type, label, path, year, session, status)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict(election_id) do update set
                    type = excluded.type,
                    label = excluded.label,
                    path = excluded.path,
                    year = excluded.year,
                    session = excluded.session,
                    status = excluded.status,
                    updated_at = current_timestamp
                """,
                (
                    election["election_id"],
                    election["type"],
                    election["label"],
                    str(election["path"]),
                    election.get("year"),
                    election.get("session"),
                    election.get("status", "todo"),
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
                    mode = excluded.mode,
                    decided_at = current_timestamp
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
                insert into source_records(source_record_id, election_id, name, birthday, payload)
                values (%s, %s, %s, %s, %s)
                on conflict(source_record_id) do update set
                    election_id = excluded.election_id,
                    name = excluded.name,
                    birthday = excluded.birthday,
                    payload = excluded.payload,
                    imported_at = current_timestamp
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
            return conn.execute(
                """
                select source_record_id, election_id, name, birthday, payload
                from source_records
                where source_record_id = %s
                """,
                (source_record_id,),
            ).fetchone()

    def list_unresolved_records(self, election_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select sr.source_record_id, sr.election_id, sr.name, sr.birthday, sr.payload
                from source_records sr
                left join resolutions r on r.source_record_id = sr.source_record_id
                where sr.election_id = %s and r.source_record_id is null
                order by sr.source_record_id
                """,
                (election_id,),
            ).fetchall()
        return list(rows)

    def iter_resolved_records(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select
                    r.candidate_id,
                    r.mode,
                    sr.source_record_id,
                    sr.election_id,
                    sr.name,
                    sr.birthday,
                    sr.payload
                from resolutions r
                join source_records sr on sr.source_record_id = r.source_record_id
                where r.candidate_id is not null
                order by sr.election_id, sr.source_record_id
                """
            ).fetchall()
        return list(rows)

    def append_operation_log(
        self,
        *,
        action: str,
        election_id: str | None = None,
        source_record_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into operation_logs(election_id, source_record_id, action, payload)
                values (%s, %s, %s, %s)
                """,
                (election_id, source_record_id, action, Jsonb(payload or {})),
            )

    def delete_election(self, election_id: str) -> None:
        with self.connect() as conn:
            conn.execute("delete from elections where election_id = %s", (election_id,))
