from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.middleware.api_key_auth import require_external_api_key
from app.services.order_selection_service import find_latest_order_for_contact, verify_selected_order
from app.utils import error_detail

router = APIRouter(dependencies=[Depends(require_external_api_key)])


@router.post("/latest")
async def latest(payload: dict[str, Any]):
    try:
        return await find_latest_order_for_contact(
            phone=payload.get("phone") or payload.get("customerPhone"),
            email=payload.get("email") or payload.get("customerEmail"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))


@router.post("/verify")
async def verify(payload: dict[str, Any]):
    try:
        result = await verify_selected_order(
            order_id=payload.get("orderId") or payload.get("order_id"),
            current_phone=payload.get("currentPhone") or payload.get("customerPhone") or payload.get("phone"),
            verification_phone=payload.get("verificationPhone") or payload.get("registeredPhone"),
        )
        if result.get("success") is False:
            raise HTTPException(status_code=400, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))
