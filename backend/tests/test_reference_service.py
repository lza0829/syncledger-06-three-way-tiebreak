"""Third-reference tiebreak: persisted batch behaviour and consistency checks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import reconcile_service as svc


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _demo_pair_id() -> int:
    for pair in svc.list_pairs():
        if pair["code"] == "retail_price_web_vs_pos":
            return pair["id"]
    raise AssertionError("demo pair missing")


def _run(client, pair_id: int, policy: str, target: str) -> dict:
    resp = client.put(
        f"/api/pairs/{pair_id}/reference",
        json={
            "reference_fixture": "retail_price_master.json",
            "reference_policy": policy,
            "reference_target_side": target,
        },
    )
    assert resp.status_code == 200, resp.text
    run = client.post("/api/reconcile", json={"pair_id": pair_id})
    assert run.status_code == 200, run.text
    return run.json()


def _summary(client, batch_id: int) -> dict:
    resp = client.get(f"/api/batches/{batch_id}/reference-summary")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_demo_pair_seeded_with_reference():
    pair_id = _demo_pair_id()
    pair = [p for p in svc.list_pairs() if p["id"] == pair_id][0]
    assert pair["reference_fixture"] == "retail_price_master.json"


def test_annotate_only_batch_counts_consistent(client):
    pair_id = _demo_pair_id()
    batch = _run(client, pair_id, "annotate_only", "right")
    summary = _summary(client, batch["id"])
    assert summary["consistent"] is True
    # P-200, P-300 and P-500 are adjudicated; P-400 diverges; P-600 awaits.
    assert summary["counts"]["reference_hit"] == 3
    assert summary["counts"]["reference_awaiting"] == 1
    assert summary["counts"]["reference_divergent"] == 1
    assert summary["counts"]["overwrite_applied"] == 0
    assert summary["batch"]["reference_policy"] == "annotate_only"


def test_reference_wins_batch_overwrites_target_and_keeps_counts_consistent(client):
    pair_id = _demo_pair_id()
    batch = _run(client, pair_id, "reference_wins", "right")
    summary = _summary(client, batch["id"])
    assert summary["consistent"] is True
    assert summary["counts"]["reference_hit"] == 3
    assert summary["counts"]["overwrite_applied"] == 3
    adjudicated = summary["buckets"]["adjudicated"]
    by_sku = {d["align_key"]["sku_code"]: d for d in adjudicated}
    # P-200 reference equals left (12.00) -> right overwritten.
    assert by_sku["P-200"]["decision"]["effective_right"]["price"] == 12.00
    # P-300 reference equals right (90.00) -> right unchanged, still adjudicated.
    assert by_sku["P-300"]["decision"]["fields"][0]["changed"] is False
    # P-500 mixes sides: price matches left (66.00), currency matches right
    # (USD); the right side only changes on price.
    p500_fields = {f["field"]: f for f in by_sku["P-500"]["decision"]["fields"]}
    assert p500_fields["price"]["ref_matches"] == "left"
    assert p500_fields["currency"]["ref_matches"] == "right"
    assert by_sku["P-500"]["decision"]["effective_right"] == {
        "sku_code": "P-500",
        "price": 66.00,
        "currency": "USD",
        "updated_at": "2026-11-12T06:10:00Z",
    }
    assert p500_fields["price"]["changed"] is True
    assert p500_fields["currency"]["changed"] is False
    for d in adjudicated:
        assert d["decision"]["overwrite_side"] == "right"


def test_divergent_and_awaiting_rows_never_carry_an_overwrite(client):
    pair_id = _demo_pair_id()
    batch = _run(client, pair_id, "reference_wins", "left")
    summary = _summary(client, batch["id"])
    for status in ("reference_divergence", "awaiting_reference"):
        for d in summary["buckets"][status]:
            assert (d.get("decision") or {}).get("overwrite_applied") is False
            assert (d.get("decision") or {}).get("overwrite_side") is None
    # The divergent row must not be silently replaced by either side value.
    divergent = summary["buckets"]["reference_divergence"][0]
    assert divergent["decision"]["effective_left"] == divergent["left"]
    assert divergent["decision"]["effective_right"] == divergent["right"]


def test_unmounted_reference_yields_no_reference_status(client):
    pair_id = _demo_pair_id()
    resp = client.put(
        f"/api/pairs/{pair_id}/reference",
        json={"reference_fixture": None, "reference_policy": "annotate_only"},
    )
    assert resp.status_code == 200, resp.text
    batch = client.post("/api/reconcile", json={"pair_id": pair_id}).json()
    summary = _summary(client, batch["id"])
    assert summary["counts"]["reference_hit"] == 0
    assert summary["counts"]["reference_awaiting"] == 0
    assert summary["counts"]["reference_divergent"] == 0
    # Restore the demo config so later runs are unaffected.
    client.put(
        f"/api/pairs/{pair_id}/reference",
        json={"reference_fixture": "retail_price_master.json", "reference_policy": "annotate_only"},
    )


def test_reference_config_rejects_bad_input(client):
    pair_id = _demo_pair_id()
    bad_policy = client.put(
        f"/api/pairs/{pair_id}/reference",
        json={"reference_fixture": "retail_price_master.json", "reference_policy": "record_only"},
    )
    assert bad_policy.status_code == 422
    bad_side = client.put(
        f"/api/pairs/{pair_id}/reference",
        json={"reference_fixture": "retail_price_master.json", "reference_target_side": "both"},
    )
    assert bad_side.status_code == 422
    traversal = client.put(
        f"/api/pairs/{pair_id}/reference",
        json={"reference_fixture": "../fixtures/retail_price_master.json"},
    )
    assert traversal.status_code == 400
    restore = client.put(
        f"/api/pairs/{pair_id}/reference",
        json={
            "reference_fixture": "retail_price_master.json",
            "reference_policy": "annotate_only",
            "reference_target_side": "right",
        },
    )
    assert restore.status_code == 200


def test_reference_fixture_catalogue(client):
    resp = client.get("/api/reference/fixtures")
    assert resp.status_code == 200
    names = {f["name"] for f in resp.json()}
    assert "retail_price_master.json" in names
    assert all("/" not in n for n in names)


def test_diff_list_exposes_reference_status(client):
    pair_id = _demo_pair_id()
    batch = _run(client, pair_id, "annotate_only", "right")
    resp = client.get(f"/api/diffs?batch_id={batch['id']}")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("reference_status" in r for r in rows)
    statuses = {r["reference_status"] for r in rows}
    assert "reference_divergence" in statuses and "awaiting_reference" in statuses
    assert "not_applicable" in statuses  # left-only P-800 / right-only P-700
