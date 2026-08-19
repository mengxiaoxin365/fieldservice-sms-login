from __future__ import annotations

from typing import Any, Protocol

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .infrai_sms import InfraiError, InfraiSmsClient
from .work_order_access import WorkOrder, WorkOrderPhoto, record_site_visit


class SmsGateway(Protocol):
    def request_code(self, to: str, request_id: str) -> dict[str, Any]:
        """Request a one-time code."""

    def verify_code(self, to: str, code: str, request_id: str) -> dict[str, Any]:
        """Verify a one-time code."""


class CodeRequest(BaseModel):
    phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    request_id: str = Field(min_length=8, max_length=100)


class CodeVerification(CodeRequest):
    code: str = Field(pattern=r"^\d{4,8}$")


class SiteVisitRequest(BaseModel):
    order: WorkOrder
    photos: list[WorkOrderPhoto]
    follow_up_note: str | None = Field(default=None, max_length=500)


def sms_gateway() -> SmsGateway:
    return InfraiSmsClient()


service = FastAPI(title="Field-service technician access")


@service.post("/login/code", status_code=202)
def send_login_code(
    request: CodeRequest, gateway: SmsGateway = Depends(sms_gateway)
) -> dict[str, str]:
    try:
        gateway.request_code(request.phone_number, request.request_id)
    except InfraiError as exc:
        raise HTTPException(status_code=_client_status(exc), detail=exc.detail) from exc
    return {"status": "code_sent"}


@service.post("/login/verify")
def verify_login_code(
    request: CodeVerification, gateway: SmsGateway = Depends(sms_gateway)
) -> dict[str, str]:
    try:
        gateway.verify_code(request.phone_number, request.code, request.request_id)
    except InfraiError as exc:
        raise HTTPException(status_code=_client_status(exc), detail=exc.detail) from exc
    return {"status": "verified"}


@service.post("/work-orders/site-visit", response_model=WorkOrder)
def complete_site_visit(request: SiteVisitRequest) -> WorkOrder:
    try:
        return record_site_visit(request.order, request.photos, request.follow_up_note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _client_status(exc: InfraiError) -> int:
    return exc.status_code if 400 <= exc.status_code < 500 else 502
