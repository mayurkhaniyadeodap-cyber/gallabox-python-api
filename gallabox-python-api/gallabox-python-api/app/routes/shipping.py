from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.integrations.ship_panel_client import get_ship_panel_tracking
from app.middleware.api_key_auth import require_external_api_key
from app.services.existing_ticket_guard_service import attach_existing_ticket_if_any
from app.services.shipment_flow_service import resolve_shipment_flow
from app.utils import error_detail

router = APIRouter(dependencies=[Depends(require_external_api_key)])


@router.post("/tracking")
async def tracking(payload: dict[str, Any]):
    try:
        return await get_ship_panel_tracking(payload.get("trackWith") or payload.get("track_with"), payload.get("refNo") or payload.get("ref_no"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))


@router.post("/shipment-flow")
async def shipment_flow(payload: dict[str, Any]):
    try:
        result = await resolve_shipment_flow(payload or {})
        if result.get("success") is False:
            raise HTTPException(status_code=400, detail=result)
        return await attach_existing_ticket_if_any(result, payload or {})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))
