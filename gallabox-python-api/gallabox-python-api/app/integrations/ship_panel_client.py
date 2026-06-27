from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings

TRACK_WITH_VALUES = {"awb", "order_no", "customer_contact"}


async def get_ship_panel_tracking(track_with: str | None, ref_no: str | None) -> dict[str, Any]:
    normalized_track_with = (track_with or "").strip().lower()
    normalized_ref_no = (ref_no or "").strip()

    if normalized_track_with not in TRACK_WITH_VALUES:
        return {
            "success": False,
            "found": False,
            "code": "INVALID_TRACK_WITH",
            "message": "trackWith must be one of awb, order_no, or customer_contact.",
        }

    if not normalized_ref_no:
        return {
            "success": False,
            "found": False,
            "code": "MISSING_REF_NO",
            "message": "refNo is required.",
        }

    if not settings.ship_panel_app_secret:
        raise RuntimeError("Ship Panel app secret is not configured. Please set SHIP_PANEL_APP_SECRET.")

    headers = {"app-secret": settings.ship_panel_app_secret}
    if settings.ship_panel_referer:
        headers["referer"] = settings.ship_panel_referer

    timeout = settings.ship_panel_timeout_ms / 1000
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                settings.ship_panel_tracking_url,
                headers=headers,
                data={"track_with": normalized_track_with, "ref_no": normalized_ref_no},
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Ship Panel request timed out while connecting to {settings.ship_panel_tracking_url}.") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ship Panel request failed before response: {exc.__class__.__name__}.") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Ship Panel request failed with status {response.status_code}.")

    payload = response.json()
    return normalize_ship_panel_response(payload)


def normalize_ship_panel_response(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    tracking = None
    if data:
        awb = data.get("awb")
        order_info = data.get("order_info") or {}
        tracking = {
            "orderNo": data.get("order_no"),
            "awb": awb,
            "trackingUrl": build_tracking_url(awb),
            "courier": data.get("courier"),
            "orderStatus": data.get("order_status"),
            "orderInfo": {
                "orderNo": order_info.get("order_no"),
                "orderDate": order_info.get("orde_date") or order_info.get("order_date"),
                "edd": order_info.get("edd"),
                "paymentMode": order_info.get("payment_mode"),
                "buyerName": order_info.get("buyer_name"),
                "contact": order_info.get("contact"),
                "address": order_info.get("address"),
            },
            "scans": [
                {
                    "message": scan.get("scan_message"),
                    "location": scan.get("scan_location"),
                    "scannedAt": scan.get("scan_at"),
                }
                for scan in data.get("scans", [])
            ],
        }

    return {
        "success": bool(payload.get("success")),
        "found": bool(payload.get("success") and data),
        "message": payload.get("message"),
        "tracking": tracking,
        "raw": payload,
    }


def build_tracking_url(awb: str | None) -> str | None:
    if not awb or not settings.ship_panel_public_tracking_base_url:
        return None
    return f"{settings.ship_panel_public_tracking_base_url.rstrip('/')}/{quote(str(awb).strip())}"
