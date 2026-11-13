from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.reconcile import (
    REFERENCE_POLICIES,
    REFERENCE_TARGET_SIDES,
    STATUS_ADJUDICATED,
    STATUS_AWAITING,
    STATUS_DIVERGENCE,
    STATUS_NO_REFERENCE,
    STATUS_NOT_APPLICABLE,
    compare_sides,
)
from app.repositories import batches as batch_repo
from app.repositories import contracts as contract_repo
from app.repositories import pairs as pair_repo
from app.repositories import tickets as ticket_repo


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"fixture {name} must be a JSON array")
    return data


def list_reference_fixtures() -> list[dict[str, Any]]:
    """Local fixture files that may be mounted as a third reference.

    Names only (never paths) so nothing outside FIXTURES_DIR can be addressed.
    """
    out = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            row_count = len(data) if isinstance(data, list) else None
        except (OSError, json.JSONDecodeError):
            row_count = None
        out.append({"name": path.name, "row_count": row_count})
    return out


def _validate_reference_payload(
    *,
    reference_fixture: str | None,
    reference_policy: str,
    reference_target_side: str,
) -> None:
    if reference_policy not in REFERENCE_POLICIES:
        raise ValueError(f"unknown reference policy: {reference_policy}")
    if reference_target_side not in REFERENCE_TARGET_SIDES:
        raise ValueError(f"unknown reference target side: {reference_target_side}")
    if reference_fixture is not None:
        allowed = {f["name"] for f in list_reference_fixtures()}
        if reference_fixture not in allowed:
            raise ValueError(f"reference fixture not available: {reference_fixture}")


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "pair_count": conn.execute("SELECT COUNT(*) c FROM reconcile_pairs").fetchone()["c"],
            "enabled_pairs": conn.execute(
                "SELECT COUNT(*) c FROM reconcile_pairs WHERE enabled=1"
            ).fetchone()["c"],
            "batch_count": conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"],
            "diff_count": conn.execute("SELECT COUNT(*) c FROM reconcile_diffs").fetchone()["c"],
            "open_dispositions": conn.execute(
                "SELECT COUNT(*) c FROM diff_tickets WHERE status='open'"
            ).fetchone()["c"],
            "policy": conn.execute(
                "SELECT value FROM settings WHERE key='default_policy'"
            ).fetchone()["value"],
        }
    finally:
        conn.close()


def list_pairs() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return pair_repo.list_pairs(conn)
    finally:
        conn.close()


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = batch_repo.list_batches(conn, limit=limit)
        pairs = {p["id"]: p for p in pair_repo.list_pairs(conn)}
        for r in rows:
            p = pairs.get(r["pair_id"])
            r["pair_code"] = p["code"] if p else None
            r["pair_title"] = p["title"] if p else None
        return rows
    finally:
        conn.close()


def list_diffs(batch_id: int | None = None, pair_id: int | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_diffs(conn, batch_id=batch_id, pair_id=pair_id)
    finally:
        conn.close()


def list_dispositions() -> list[dict[str, Any]]:
    """Difference disposition records (not a customer-service ticket desk)."""
    conn = connect()
    try:
        return ticket_repo.list_tickets(conn)
    finally:
        conn.close()


def list_contracts() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return contract_repo.list_contracts(conn)
    finally:
        conn.close()


def list_settings() -> dict[str, str]:
    conn = connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


def update_pair_reference(pair_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach / detach the third reference and choose the adjudication policy.

    Reference mounting and policy are mutually exclusive per pair: either the
    policy is ``reference_wins`` (overwrite the configured side) or
    ``annotate_only`` (annotate, never overwrite). Both are stored even when no
    fixture is mounted, so re-mounting keeps the last choice.
    """
    reference_fixture = payload.get("reference_fixture") or None
    reference_name = payload.get("reference_name") or None
    reference_policy = payload.get("reference_policy") or "annotate_only"
    reference_target_side = payload.get("reference_target_side") or "right"
    _validate_reference_payload(
        reference_fixture=reference_fixture,
        reference_policy=reference_policy,
        reference_target_side=reference_target_side,
    )
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, pair_id)
        if not pair:
            raise ValueError("pair not found")
        if reference_fixture and reference_name is None:
            reference_name = reference_fixture
        updated = pair_repo.update_reference(
            conn,
            pair_id,
            reference_fixture=reference_fixture,
            reference_name=reference_name,
            reference_policy=reference_policy,
            reference_target_side=reference_target_side,
        )
        conn.commit()
        assert updated is not None
        return updated
    finally:
        conn.close()


def run_reconcile(pair_id: int, note: str | None = None) -> dict[str, Any]:
    """Extract both fixtures, align, persist batch + diffs.

    Base behavior stays record-only. When the pair has a reference fixture
    mounted, field conflicts are adjudicated according to the pair's policy;
    the overwrite is recorded in the batch decision log, never written back to
    the fixture files.
    """
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, pair_id)
        if not pair:
            raise ValueError("pair not found")
        if not pair["enabled"]:
            raise ValueError("pair disabled")

        left_rows = _load_fixture(pair["left_fixture"])
        right_rows = _load_fixture(pair["right_fixture"])
        reference_fixture = pair.get("reference_fixture")
        reference_rows = (
            _load_fixture(reference_fixture) if reference_fixture else None
        )
        policy = pair.get("reference_policy") or "annotate_only"
        target_side = pair.get("reference_target_side") or "right"
        result = compare_sides(
            left_rows,
            right_rows,
            align_keys=pair["align_keys"],
            compare_fields=pair["compare_fields"],
            reference_rows=reference_rows,
            reference_policy=policy,
            reference_target_side=target_side,
        )
        now = _now()
        seq = conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"] + 1
        batch_no = f"RB-{now[:10].replace('-', '')}-{seq:04d}"
        batch_id = batch_repo.insert_batch(
            conn,
            batch_no=batch_no,
            pair_id=pair_id,
            status="completed",
            counts=result["counts"],
            note=note,
            created_at=now,
            reference={
                "configured": result["reference"]["configured"],
                "fixture": reference_fixture,
                "policy": policy if reference_fixture else None,
                "target_side": target_side if reference_fixture else None,
            },
        )
        for diff in result["diffs"]:
            if diff["kind"] == "matched":
                continue
            batch_repo.insert_diff(
                conn, batch_id=batch_id, pair_id=pair_id, diff=diff, created_at=now
            )
        conn.commit()
        batch = batch_repo.get_batch(conn, batch_id)
        assert batch is not None
        batch["pair_code"] = pair["code"]
        batch["pair_title"] = pair["title"]
        batch["policy"] = "record_only"
        batch["counts"] = result["counts"]
        batch["reference"] = result["reference"]
        batch["diff_preview"] = batch_repo.list_diffs(conn, batch_id=batch_id, limit=20)
        return batch
    finally:
        conn.close()


REFERENCE_BUCKETS = ("adjudicated", "awaiting_reference", "reference_divergence", "no_reference", "not_applicable")


def batch_reference_summary(batch_id: int) -> dict[str, Any]:
    """Batch reference counts plus the per-bucket diff list and a consistency check.

    The consistency check recomputes the three reference counters straight from
    ``reconcile_diffs`` and compares them with the stored batch columns, so the
    numbers on the page can always be reconciled against the diff list.
    """
    conn = connect()
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if not batch:
            raise ValueError("batch not found")
        pair = pair_repo.get_pair(conn, batch["pair_id"])
        diffs = batch_repo.list_diffs(conn, batch_id=batch_id)
        recomputed = {
            "reference_hit": sum(1 for d in diffs if d["reference_status"] == STATUS_ADJUDICATED),
            "reference_awaiting": sum(1 for d in diffs if d["reference_status"] == STATUS_AWAITING),
            "reference_divergent": sum(1 for d in diffs if d["reference_status"] == STATUS_DIVERGENCE),
        }
        checks = [
            {
                "key": key,
                "stored": batch.get(key, 0),
                "recomputed": value,
                "ok": batch.get(key, 0) == value,
            }
            for key, value in recomputed.items()
        ]
        buckets = {b: [] for b in REFERENCE_BUCKETS}
        for d in diffs:
            buckets.setdefault(d["reference_status"], []).append(d)
        overwritten = [
            d
            for d in diffs
            if (d.get("decision") or {}).get("overwrite_applied")
        ]
        return {
            "batch": batch,
            "pair": pair,
            "counts": {
                "diff_total": len(diffs),
                "reference_hit": recomputed["reference_hit"],
                "reference_awaiting": recomputed["reference_awaiting"],
                "reference_divergent": recomputed["reference_divergent"],
                "no_reference": len(buckets.get(STATUS_NO_REFERENCE, [])),
                "not_applicable": len(buckets.get(STATUS_NOT_APPLICABLE, [])),
                "overwrite_applied": len(overwritten),
            },
            "stored": {key: batch.get(key, 0) for key in recomputed},
            "checks": checks,
            "consistent": all(c["ok"] for c in checks),
            "buckets": buckets,
            "diffs": diffs,
        }
    finally:
        conn.close()


def audit_summary(batch_id: int) -> dict[str, Any]:
    """Lightweight audit view for a batch (export hooks left for later cuts)."""
    conn = connect()
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if not batch:
            raise ValueError("batch not found")
        pair = pair_repo.get_pair(conn, batch["pair_id"])
        diffs = batch_repo.list_diffs(conn, batch_id=batch_id)
        return {
            "batch": batch,
            "pair": pair,
            "diff_count": len(diffs),
            "kinds": {
                "left_only": sum(1 for d in diffs if d["kind"] == "left_only"),
                "right_only": sum(1 for d in diffs if d["kind"] == "right_only"),
                "field_mismatch": sum(1 for d in diffs if d["kind"] == "field_mismatch"),
            },
            "reference_counts": {
                "hit": batch.get("reference_hit", 0),
                "awaiting": batch.get("reference_awaiting", 0),
                "divergent": batch.get("reference_divergent", 0),
            },
            "export_ready": False,
            "note": "底座仅提供摘要；审计包导出留给后题切口",
        }
    finally:
        conn.close()

