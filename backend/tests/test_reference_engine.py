"""Third-reference tiebreak: engine-level semantics."""

from __future__ import annotations

import pytest

from app.engines.reconcile import (
    STATUS_ADJUDICATED,
    STATUS_AWAITING,
    STATUS_DIVERGENCE,
    STATUS_NO_REFERENCE,
    STATUS_NOT_APPLICABLE,
    compare_sides,
)

ALIGN = ["sku_code"]
FIELDS = ["price", "currency"]


def _row(sku, price, currency="CNY"):
    return {"sku_code": sku, "price": price, "currency": currency}


def run(
    left,
    right,
    reference=None,
    *,
    policy="annotate_only",
    target="right",
):
    return compare_sides(
        left,
        right,
        align_keys=ALIGN,
        compare_fields=FIELDS,
        reference_rows=reference,
        reference_policy=policy,
        reference_target_side=target,
    )


def one(result, sku):
    diffs = [d for d in result["diffs"] if d["align_key"]["sku_code"] == sku]
    assert len(diffs) == 1, f"expected one diff for {sku}: {diffs}"
    return diffs[0]


def test_agreement_never_consults_reference():
    # Reference deliberately disagrees; the row must stay matched with no
    # reference status at all.
    result = run([_row("A", 10)], [_row("A", 10)], [_row("A", 99)])
    assert result["counts"]["matched"] == 1
    assert result["diffs"] == []
    assert result["counts"]["reference_hit"] == 0


def test_conflict_reference_equals_left_annotate_only():
    result = run([_row("A", 10)], [_row("A", 20)], [_row("A", 10)])
    diff = one(result, "A")
    assert diff["reference_status"] == STATUS_ADJUDICATED
    assert diff["decision"]["policy"] == "annotate_only"
    assert diff["decision"]["overwrite_side"] is None
    assert diff["decision"]["overwrite_applied"] is False
    assert diff["decision"]["fields"][0]["ref_matches"] == "left"
    assert diff["decision"]["effective_left"]["price"] == 10
    assert diff["decision"]["effective_right"]["price"] == 20
    assert result["counts"]["reference_hit"] == 1


def test_reference_wins_overwrites_target_side_with_reference_value():
    # Reference equals left; policy overwrites the configured target (right).
    result = run(
        [_row("A", 10)], [_row("A", 20)], [_row("A", 10)], policy="reference_wins", target="right"
    )
    diff = one(result, "A")
    decision = diff["decision"]
    assert decision["overwrite_side"] == "right"
    assert decision["overwrite_applied"] is True
    assert decision["effective_left"]["price"] == 10
    assert decision["effective_right"]["price"] == 10
    field = decision["fields"][0]
    assert field["before"] == 20 and field["after"] == 10 and field["changed"] is True
    # Original captured side snapshot is untouched.
    assert diff["right"]["price"] == 20


def test_reference_wins_target_left():
    result = run(
        [_row("A", 10)], [_row("A", 20)], [_row("A", 20)], policy="reference_wins", target="left"
    )
    diff = one(result, "A")
    decision = diff["decision"]
    assert decision["overwrite_side"] == "left"
    assert decision["effective_left"]["price"] == 20
    assert decision["effective_right"]["price"] == 20
    assert diff["left"]["price"] == 10


def test_reference_divergence_never_overwrites_under_either_policy():
    for policy in ("annotate_only", "reference_wins"):
        result = run([_row("A", 10)], [_row("A", 20)], [_row("A", 30)], policy=policy)
        diff = one(result, "A")
        assert diff["reference_status"] == STATUS_DIVERGENCE
        assert diff["decision"]["overwrite_applied"] is False
        assert diff["decision"]["divergent_fields"] == ["price"]
        assert result["counts"]["reference_divergent"] == 1
        assert result["counts"]["reference_hit"] == 0


def test_missing_reference_key_is_awaiting_not_adjudicated():
    result = run([_row("A", 10)], [_row("A", 20)], [_row("B", 10)], policy="reference_wins")
    diff = one(result, "A")
    assert diff["reference_status"] == STATUS_AWAITING
    assert diff["decision"]["missing_reference"] is True
    assert diff["decision"]["overwrite_applied"] is False
    assert result["counts"]["reference_awaiting"] == 1
    assert result["counts"]["reference_hit"] == 0


def test_reference_missing_compared_field_is_awaiting():
    reference = [{"sku_code": "A", "price": 10}]  # no currency
    result = run([_row("A", 10, "CNY")], [_row("A", 10, "USD")], reference)
    diff = one(result, "A")
    assert diff["reference_status"] == STATUS_AWAITING
    assert diff["decision"]["missing_fields"] == ["currency"]
    assert diff["decision"]["overwrite_applied"] is False


def test_side_only_rows_do_not_touch_reference():
    result = run([_row("A", 10)], [_row("B", 20)], [_row("C", 30)])
    assert [d["reference_status"] for d in result["diffs"]] == [
        STATUS_NOT_APPLICABLE,
        STATUS_NOT_APPLICABLE,
    ]
    counts = result["counts"]
    assert counts["left_only"] == 1 and counts["right_only"] == 1
    assert counts["reference_hit"] == counts["reference_awaiting"] == counts["reference_divergent"] == 0


def test_mixed_fields_can_match_different_sides():
    left = {"sku_code": "A", "price": 10, "currency": "CNY"}
    right = {"sku_code": "A", "price": 20, "currency": "USD"}
    reference = {"sku_code": "A", "price": 10, "currency": "USD"}
    result = run([left], [right], [reference], policy="reference_wins", target="right")
    diff = one(result, "A")
    fields = {f["field"]: f for f in diff["decision"]["fields"]}
    assert fields["price"]["ref_matches"] == "left"
    assert fields["currency"]["ref_matches"] == "right"
    assert diff["reference_status"] == STATUS_ADJUDICATED
    assert diff["decision"]["effective_right"] == {"sku_code": "A", "price": 10, "currency": "USD"}


def test_no_reference_configured_keeps_conflicts_unadjudicated():
    result = run([_row("A", 10)], [_row("A", 20)])
    diff = one(result, "A")
    assert diff["reference_status"] == STATUS_NO_REFERENCE
    assert diff["decision"] is None
    assert result["counts"]["reference_hit"] == 0


def test_counts_always_match_emitted_diff_rows():
    left = [_row("A", 10), _row("B", 20), _row("C", 30), _row("D", 40), _row("E", 50), _row("F", 60)]
    right = [_row("A", 10), _row("B", 20), _row("C", 40), _row("D", 50), _row("E", 70), _row("G", 80)]
    reference = [
        _row("A", 99),
        _row("B", 20),
        _row("C", 30),
        _row("D", 999),
        _row("F", 60),
        _row("G", 80),
    ]
    for policy in ("annotate_only", "reference_wins"):
        result = run(left, right, reference, policy=policy, target="left")
        diffs = result["diffs"]
        counts = result["counts"]
        assert counts["reference_hit"] == sum(
            1 for d in diffs if d["reference_status"] == STATUS_ADJUDICATED
        )
        assert counts["reference_awaiting"] == sum(
            1 for d in diffs if d["reference_status"] == STATUS_AWAITING
        )
        assert counts["reference_divergent"] == sum(
            1 for d in diffs if d["reference_status"] == STATUS_DIVERGENCE
        )
        assert counts["diff_total"] == len(diffs)


def test_invalid_policy_or_side_rejected():
    with pytest.raises(ValueError):
        run([], [], policy="first_wins")
    with pytest.raises(ValueError):
        run([], [], target="middle")


def test_single_divergent_field_blocks_row_even_if_other_matches():
    left = {"sku_code": "A", "price": 10, "currency": "CNY"}
    right = {"sku_code": "A", "price": 20, "currency": "USD"}
    reference = {"sku_code": "A", "price": 10, "currency": "EUR"}  # price ok, currency diverges
    result = run([left], [right], [reference], policy="reference_wins", target="right")
    diff = one(result, "A")
    assert diff["reference_status"] == STATUS_DIVERGENCE
    assert diff["decision"]["overwrite_applied"] is False
    assert diff["decision"]["effective_right"]["price"] == 20
    assert diff["decision"]["divergent_fields"] == ["currency"]
