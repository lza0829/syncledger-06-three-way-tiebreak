from __future__ import annotations

import json
from typing import Any

import sqlite3

REFERENCE_FIELDS = (
    "reference_fixture",
    "reference_name",
    "reference_policy",
    "reference_target_side",
)


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["align_keys"] = json.loads(d.pop("align_keys_json"))
    d["compare_fields"] = json.loads(d.pop("compare_fields_json"))
    d["enabled"] = bool(d["enabled"])
    return d


def list_pairs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM reconcile_pairs ORDER BY id").fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def get_pair(conn: sqlite3.Connection, pair_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM reconcile_pairs WHERE id=?", (pair_id,)).fetchone())


def get_pair_by_code(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM reconcile_pairs WHERE code=?", (code,)).fetchone())


def update_reference(
    conn: sqlite3.Connection,
    pair_id: int,
    *,
    reference_fixture: str | None,
    reference_name: str | None,
    reference_policy: str,
    reference_target_side: str,
) -> dict[str, Any] | None:
    conn.execute(
        """
        UPDATE reconcile_pairs
        SET reference_fixture=?, reference_name=?, reference_policy=?, reference_target_side=?
        WHERE id=?
        """,
        (reference_fixture, reference_name, reference_policy, reference_target_side, pair_id),
    )
    return get_pair(conn, pair_id)
