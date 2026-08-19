from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class DispatchStatus(str, Enum):
    ASSIGNED = "assigned"
    EN_ROUTE = "en_route"
    ON_SITE = "on_site"
    FOLLOW_UP = "follow_up"
    CLOSED = "closed"


class WorkOrderPhoto(BaseModel):
    photo_id: UUID
    object_key: str = Field(min_length=1, max_length=240)
    captured_at: str


class TechnicianFollowUp(BaseModel):
    note: str = Field(min_length=1, max_length=500)
    required: bool = True


class WorkOrder(BaseModel):
    work_order_id: UUID
    technician_id: UUID
    dispatch_status: DispatchStatus
    photos: list[WorkOrderPhoto] = Field(default_factory=list, max_length=12)
    follow_up: TechnicianFollowUp | None = None


def record_site_visit(
    order: WorkOrder, photos: list[WorkOrderPhoto], follow_up_note: str | None
) -> WorkOrder:
    """Move an on-site order to its next reviewable state."""
    if order.dispatch_status is not DispatchStatus.ON_SITE:
        raise ValueError("site evidence can only be recorded while on site")
    if not photos:
        raise ValueError("at least one work-order photo is required")

    follow_up = (
        TechnicianFollowUp(note=follow_up_note) if follow_up_note else None
    )
    next_status = DispatchStatus.FOLLOW_UP if follow_up else DispatchStatus.CLOSED
    return order.model_copy(
        update={
            "dispatch_status": next_status,
            "photos": [*order.photos, *photos],
            "follow_up": follow_up,
        }
    )
