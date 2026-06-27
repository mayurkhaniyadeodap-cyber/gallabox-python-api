from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.middleware.api_key_auth import require_external_api_key
from app.services.customer_info_flow_service import resolve_customer_info_flow
from app.services.existing_ticket_guard_service import attach_existing_ticket_if_any
from app.utils import error_detail

router = APIRouter(dependencies=[Depends(require_external_api_key)])


@router.post("/change-flow")
async def change_flow(payload: dict[str, Any]):
    try:
        result = await resolve_customer_info_flow(payload or {})
        if result.get("success") is False:
            raise HTTPException(status_code=400, detail=result)
        return await attach_existing_ticket_if_any(result, payload or {})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))
