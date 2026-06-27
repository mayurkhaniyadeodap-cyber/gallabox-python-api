from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.integrations.shopify_client import find_shopify_order_by_customer_contact, find_shopify_order_by_order_id, find_shopify_order_ids_by_phone, get_shopify_order_refund_details
from app.middleware.api_key_auth import require_external_api_key
from app.utils import error_detail

router = APIRouter(dependencies=[Depends(require_external_api_key)])


@router.post("/order-lookup")
async def order_lookup(payload: dict[str, Any]):
    order_id = payload.get("orderId")
    email = payload.get("email")
    phone = payload.get("phone")

    if not any(str(value or "").strip() for value in [order_id, email, phone]):
        raise HTTPException(status_code=400, detail={"message": "Provide at least one of orderId, email, or phone."})

    try:
        result = await find_shopify_order_by_order_id(order_id) if order_id else await find_shopify_order_by_customer_contact(email=email, phone=phone)
        return {
            "lookup": {
                "type": "order_id" if order_id else "customer_contact",
                "orderId": str(order_id).strip() if order_id else None,
                "email": str(email).strip() if email else None,
                "phone": str(phone).strip() if phone else None,
            },
            **result,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))


@router.get("/orders-by-phone")
async def orders_by_phone(phone: str = Query(..., description="Customer phone number")):
    if not phone.strip():
        raise HTTPException(status_code=400, detail={"message": "Provide phone."})

    try:
        return await find_shopify_order_ids_by_phone(phone)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))


@router.post("/refund-details")
async def refund_details(payload: dict[str, Any]):
    order_id = payload.get("orderId")

    if not str(order_id or "").strip():
        raise HTTPException(status_code=400, detail={"message": "Provide orderId."})

    try:
        result = await get_shopify_order_refund_details(order_id)
        if result.get("found") is False:
            raise HTTPException(status_code=404, detail={
                "lookup": {
                    "type": "order_id",
                    "orderId": str(order_id).strip(),
                },
                **result,
            })
        return {
            "lookup": {
                "type": "order_id",
                "orderId": str(order_id).strip(),
            },
            **result,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=error_detail(exc))
