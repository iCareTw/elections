from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from psycopg import sql

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.webapp.store import Store


def _list_tables(conn: Any) -> list[str]:
    rows = conn.execute(
        """
        select table_name
        from information_schema.tables
        where table_schema = current_schema()
          and table_type = 'BASE TABLE'
        order by table_name
        """
    ).fetchall()
    return [row["table_name"] for row in rows]


def _foreign_key_edges(conn: Any) -> set[tuple[str, str]]:
    rows = conn.execute(
        """
        select
            child.relname as child_table,
            parent.relname as parent_table
        from pg_constraint constraint_info
        join pg_class child on child.oid = constraint_info.conrelid
        join pg_class parent on parent.oid = constraint_info.confrelid
        join pg_namespace child_namespace on child_namespace.oid = child.relnamespace
        join pg_namespace parent_namespace on parent_namespace.oid = parent.relnamespace
        where constraint_info.contype = 'f'
          and child_namespace.nspname = current_schema()
          and parent_namespace.nspname = current_schema()
        """,
    ).fetchall()
    return {(row["child_table"], row["parent_table"]) for row in rows}


def _delete_order(tables: list[str], edges: set[tuple[str, str]]) -> list[str]:
    remaining = set(tables)
    order: list[str] = []

    while remaining:
        leaves = sorted(
            table
            for table in remaining
            if not any(parent == table and child in remaining for child, parent in edges)
        )
        if not leaves:
            raise RuntimeError("Could not determine safe delete order because table dependencies contain a cycle")
        order.extend(leaves)
        remaining.difference_update(leaves)

    return order


def _count_rows(conn: Any, table: str) -> int:
    query = sql.SQL("select count(*)::int as n from {}").format(sql.Identifier(table))
    return conn.execute(query).fetchone()["n"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete all table data in the elections schema without dropping tables."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete rows. Without this flag, only prints current row counts.",
    )
    args = parser.parse_args()

    with Store().connect() as conn:
        tables = _list_tables(conn)
        delete_order = _delete_order(tables, _foreign_key_edges(conn))
        before = {table: _count_rows(conn, table) for table in tables}

        if args.yes:
            for table in delete_order:
                conn.execute(sql.SQL("delete from {}").format(sql.Identifier(table)))
            after = {table: _count_rows(conn, table) for table in tables}
            conn.commit()
        else:
            after = before

    print("mode", "delete" if args.yes else "dry-run")
    print("delete_order", delete_order)
    print("before", before)
    print("after", after)


if __name__ == "__main__":
    main()
