from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import reconcile_service as svc

router = APIRouter(tags=["reference"])


class ReferenceConfigBody(BaseModel):
    reference_fixture: str | None = None
    reference_name: str | None = None
    reference_policy: Literal["reference_wins", "annotate_only"] = "annotate_only"
    reference_target_side: Literal["left", "right"] = "right"


@router.get("/reference/fixtures")
def list_reference_fixtures():
    return svc.list_reference_fixtures()


@router.put("/pairs/{pair_id}/reference")
def update_pair_reference(pair_id: int, body: ReferenceConfigBody):
    try:
        return svc.update_pair_reference(pair_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/batches/{batch_id}/reference-summary")
def batch_reference_summary(batch_id: int):
    try:
        return svc.batch_reference_summary(batch_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
