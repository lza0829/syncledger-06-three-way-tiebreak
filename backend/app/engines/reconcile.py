"""Align two endpoint snapshots by composite key and classify diffs.

Base behavior: record mismatches only — never auto-overwrite either side.

Third-reference tiebreak (this cut):
- Only rows where left and right *conflict on fields* consult the reference.
- Left-only / right-only rows never consult it (status ``not_applicable``).
- Reference missing the align key (or a compared field) => ``awaiting_reference``.
- Reference value equal to left or right => ``adjudicated``; the selected policy
  either overwrites the configured target side with the reference value
  (``reference_wins``) or only annotates (``annotate_only``).
- Reference value differs from *both* sides => ``reference_divergence``; never
  overwritten under either policy.
- A side value is never silently presented as the adjudication.
"""

from __future__ import annotations

from typing import Any


DIFF_LEFT_ONLY = "left_only"
DIFF_RIGHT_ONLY = "right_only"
DIFF_FIELD_MISMATCH = "field_mismatch"
DIFF_MATCHED = "matched"

REFERENCE_POLICY_WINS = "reference_wins"
REFERENCE_POLICY_ANNOTATE = "annotate_only"
REFERENCE_POLICIES = (REFERENCE_POLICY_WINS, REFERENCE_POLICY_ANNOTATE)

REFERENCE_TARGET_SIDES = ("left", "right")

STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_NO_REFERENCE = "no_reference"
STATUS_AWAITING = "awaiting_reference"
STATUS_DIVERGENCE = "reference_divergence"
STATUS_ADJUDICATED = "adjudicated"

REFERENCE_SCORE_KEYS = ("reference_hit", "reference_awaiting", "reference_divergent")


def _key_tuple(row: dict[str, Any], align_keys: list[str]) -> tuple:
    return tuple(row.get(k) for k in align_keys)


def _index(rows: list[dict[str, Any]], align_keys: list[str]) -> dict[tuple, dict[str, Any]]:
    out: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        out[_key_tuple(row, align_keys)] = row
    return out


def _base_decision(
    policy: str,
    target_side: str,
    *,
    overwrite_side: str | None,
    fields: list[dict[str, Any]],
    effective_left: dict[str, Any] | None,
    effective_right: dict[str, Any] | None,
    divergent_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "policy": policy,
        "target_side": target_side,
        "overwrite_side": overwrite_side,
        "overwrite_applied": overwrite_side is not None,
        "fields": fields,
        "effective_left": effective_left,
        "effective_right": effective_right,
        "divergent_fields": divergent_fields or [],
    }


def _adjudicate_mismatch(
    *,
    left: dict[str, Any],
    right: dict[str, Any],
    reference: dict[str, Any],
    mismatched: list[str],
    policy: str,
    target_side: str,
) -> tuple[str, dict[str, Any]]:
    """Return (reference_status, decision) for a left/right field conflict."""
    fields: list[dict[str, Any]] = []
    divergent_fields: list[str] = []
    for field in mismatched:
        left_value = left.get(field)
        right_value = right.get(field)
        ref_value = reference.get(field)
        if ref_value == left_value:
            matches = "left"
        elif ref_value == right_value:
            matches = "right"
        else:
            matches = None
            divergent_fields.append(field)
        fields.append(
            {
                "field": field,
                "left": left_value,
                "right": right_value,
                "reference": ref_value,
                "ref_matches": matches,
                "overwrite": None,
                "before": None,
                "after": None,
                "changed": False,
            }
        )

    if divergent_fields:
        # Even if some fields line up with the reference, a single divergent
        # field blocks the whole row: no policy may overwrite here.
        return STATUS_DIVERGENCE, _base_decision(
            policy,
            target_side,
            overwrite_side=None,
            fields=fields,
            effective_left=dict(left),
            effective_right=dict(right),
            divergent_fields=divergent_fields,
        )

    if policy == REFERENCE_POLICY_ANNOTATE:
        return STATUS_ADJUDICATED, _base_decision(
            policy,
            target_side,
            overwrite_side=None,
            fields=fields,
            effective_left=dict(left),
            effective_right=dict(right),
        )

    overwrite_side = target_side
    effective_left = dict(left)
    effective_right = dict(right)
    for entry in fields:
        target_row = effective_right if overwrite_side == "right" else effective_left
        before = target_row.get(entry["field"])
        after = entry["reference"]
        entry["overwrite"] = overwrite_side
        entry["before"] = before
        entry["after"] = after
        entry["changed"] = before != after
        target_row[entry["field"]] = after
    return STATUS_ADJUDICATED, _base_decision(
        policy,
        target_side,
        overwrite_side=overwrite_side,
        fields=fields,
        effective_left=effective_left,
        effective_right=effective_right,
    )


def _awaiting_decision(
    *,
    policy: str,
    target_side: str,
    left: dict[str, Any],
    right: dict[str, Any],
    reference: dict[str, Any] | None,
    mismatched: list[str],
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    fields = []
    for field in mismatched:
        fields.append(
            {
                "field": field,
                "left": left.get(field),
                "right": right.get(field),
                "reference": reference.get(field) if reference is not None else None,
                "ref_matches": None,
                "overwrite": None,
                "before": None,
                "after": None,
                "changed": False,
            }
        )
    decision = _base_decision(
        policy,
        target_side,
        overwrite_side=None,
        fields=fields,
        effective_left=dict(left),
        effective_right=dict(right),
    )
    decision["missing_reference"] = reference is None
    decision["missing_fields"] = missing_fields or []
    return decision


def compare_sides(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    *,
    align_keys: list[str],
    compare_fields: list[str],
    reference_rows: list[dict[str, Any]] | None = None,
    reference_policy: str = REFERENCE_POLICY_ANNOTATE,
    reference_target_side: str = "right",
) -> dict[str, Any]:
    if reference_policy not in REFERENCE_POLICIES:
        raise ValueError(f"unknown reference policy: {reference_policy}")
    if reference_target_side not in REFERENCE_TARGET_SIDES:
        raise ValueError(f"unknown reference target side: {reference_target_side}")

    left_idx = _index(left_rows, align_keys)
    right_idx = _index(right_rows, align_keys)
    reference_idx = _index(reference_rows, align_keys) if reference_rows is not None else None
    all_keys = sorted(set(left_idx) | set(right_idx), key=lambda t: tuple(str(x) for x in t))

    diffs: list[dict[str, Any]] = []
    counts = {
        "left_rows": len(left_rows),
        "right_rows": len(right_rows),
        "matched": 0,
        "left_only": 0,
        "right_only": 0,
        "field_mismatch": 0,
        "diff_total": 0,
        "reference_hit": 0,
        "reference_awaiting": 0,
        "reference_divergent": 0,
    }

    for key in all_keys:
        left = left_idx.get(key)
        right = right_idx.get(key)
        key_obj = {k: key[i] for i, k in enumerate(align_keys)}
        if left is not None and right is None:
            counts["left_only"] += 1
            diffs.append(
                {
                    "kind": DIFF_LEFT_ONLY,
                    "align_key": key_obj,
                    "left": left,
                    "right": None,
                    "mismatched_fields": [],
                    "reference_status": STATUS_NOT_APPLICABLE,
                    "reference": None,
                    "decision": None,
                }
            )
        elif right is not None and left is None:
            counts["right_only"] += 1
            diffs.append(
                {
                    "kind": DIFF_RIGHT_ONLY,
                    "align_key": key_obj,
                    "left": None,
                    "right": right,
                    "mismatched_fields": [],
                    "reference_status": STATUS_NOT_APPLICABLE,
                    "reference": None,
                    "decision": None,
                }
            )
        else:
            mismatched = [
                f
                for f in compare_fields
                if (left or {}).get(f) != (right or {}).get(f)
            ]
            if not mismatched:
                # Left and right agree: the reference is never consulted.
                counts["matched"] += 1
                continue

            counts["field_mismatch"] += 1
            entry: dict[str, Any] = {
                "kind": DIFF_FIELD_MISMATCH,
                "align_key": key_obj,
                "left": left,
                "right": right,
                "mismatched_fields": mismatched,
                "reference": None,
                "reference_status": STATUS_NO_REFERENCE,
                "decision": None,
            }
            if reference_idx is None:
                entry["reference_status"] = STATUS_NO_REFERENCE
            else:
                reference = reference_idx.get(key)
                if reference is None:
                    entry["reference_status"] = STATUS_AWAITING
                    entry["decision"] = _awaiting_decision(
                        policy=reference_policy,
                        target_side=reference_target_side,
                        left=left or {},
                        right=right or {},
                        reference=None,
                        mismatched=mismatched,
                    )
                else:
                    missing_fields = [f for f in mismatched if f not in reference]
                    entry["reference"] = reference
                    if missing_fields:
                        entry["reference_status"] = STATUS_AWAITING
                        entry["decision"] = _awaiting_decision(
                            policy=reference_policy,
                            target_side=reference_target_side,
                            left=left or {},
                            right=right or {},
                            reference=reference,
                            mismatched=mismatched,
                            missing_fields=missing_fields,
                        )
                    else:
                        status, decision = _adjudicate_mismatch(
                            left=left or {},
                            right=right or {},
                            reference=reference,
                            mismatched=mismatched,
                            policy=reference_policy,
                            target_side=reference_target_side,
                        )
                        entry["reference_status"] = status
                        entry["decision"] = decision
            diffs.append(entry)

    counts["diff_total"] = (
        counts["left_only"] + counts["right_only"] + counts["field_mismatch"]
    )
    # Derive the reference buckets from the emitted diff rows so the numbers
    # can never drift from the list the page renders.
    counts["reference_hit"] = sum(
        1 for d in diffs if d["reference_status"] == STATUS_ADJUDICATED
    )
    counts["reference_awaiting"] = sum(
        1 for d in diffs if d["reference_status"] == STATUS_AWAITING
    )
    counts["reference_divergent"] = sum(
        1 for d in diffs if d["reference_status"] == STATUS_DIVERGENCE
    )
    return {
        "counts": counts,
        "diffs": diffs,
        "reference": {
            "configured": reference_idx is not None,
            "policy": reference_policy,
            "target_side": reference_target_side,
        },
    }
