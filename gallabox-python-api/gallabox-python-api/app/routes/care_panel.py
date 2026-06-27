from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.middleware.api_key_auth import require_external_api_key
from app.services.care_panel_ticket_service import get_open_tickets_for_customer
from app.utils import error_detail

router = APIRouter(dependencies=[Depends(require_external_api_key)])


@router.post("/open-tickets")
async def open_tickets(payload: dict[str, Any]):
    try:
        result = await get_open_tickets_for_customer(payload or {})
        if result.get("success") is False:
            raise HTTPException(status_code=400, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))
