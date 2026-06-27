from datetime import datetime
from typing import Any

from app.integrations.shopify_client import find_shopify_order_by_customer_contact, find_shopify_order_by_order_id
from app.integrations.ship_panel_client import get_ship_panel_tracking
from app.services.common import has_value, normalize_phone

FLOW = "order_selection"


async def find_latest_order_for_contact(phone: str | None, email: str | None) -> dict[str, Any]:
    if not has_value(phone) and not has_value(email):
        return build_response(False, False, "await_customer_contact", "Please share your registered mobile number or email address so we can find your latest order.", message="Phone or email is required.", missingInputs=["phoneOrEmail"])

    shopify_result = await find_shopify_order_by_customer_contact(email=email, phone=phone)
    if not shopify_result.get("found") or not shopify_result.get("order"):
        return build_response(True, False, "await_order_input", "We could not detect any order from your phone number. Please enter the order number you wish to get support on.", lookup={"phone": normalize_phone(phone) if has_value(phone) else None, "email": str(email).strip().lower() if has_value(email) else None}, upstream={"shopify": {"found": False, "message": shopify_result.get("reason")}})

    order = shopify_result["order"]
    tracking_result = await get_tracking_for_order(order)
    summary = build_order_summary(order, tracking_result.get("tracking") if tracking_result else None)
    return build_response(True, True, "confirm_latest_order", summary["displayText"], nextPrompt="Do you want help with this order, or do you want to enter another order number?", order=summary["order"], tracking=summary["tracking"], upstream={"shopify": {"found": True, "message": None}, "shipPanel": {"found": tracking_result.get("found"), "message": tracking_result.get("message")} if tracking_result else None})


async def verify_selected_order(order_id: str | None, current_phone: str | None, verification_phone: str | None) -> dict[str, Any]:
    if not has_value(order_id):
        return build_response(False, False, "await_order_input", "Please enter the order number for which you need support.", message="Order number is required.", missingInputs=["orderId"])

    shopify_result = await find_shopify_order_by_order_id(order_id)
    if not shopify_result.get("found") or not shopify_result.get("order"):
        return build_response(True, False, "order_not_found", "The inputted order number does not exist.", lookup={"orderId": str(order_id).strip()}, upstream={"shopify": {"found": False, "message": shopify_result.get("reason")}})

    order = shopify_result["order"]
    candidates = get_order_phone_candidates(order)
    if has_value(current_phone) and phone_matches_any(current_phone, candidates):
        return await build_verified_order_response(order, "current_phone_match")

    if not has_value(verification_phone):
        return build_response(True, True, "await_registered_phone_verification", "The inputted order's primary phone number does not match with your phone number. Please enter the 10 digit phone number associated with your selected order to verify.", verified=False, lookup={"orderId": str(order_id).strip(), "currentPhone": normalize_phone(current_phone) if has_value(current_phone) else None}, order={"orderNo": order.get("name")})

    if phone_matches_any(verification_phone, candidates):
        return await build_verified_order_response(order, "verification_phone_match")

    return build_response(True, True, "ownership_verification_failed", "Sorry, we cannot help you with this order because the phone number entered does not match the order owner details.", verified=False, lookup={"orderId": str(order_id).strip(), "currentPhone": normalize_phone(current_phone) if has_value(current_phone) else None, "verificationPhone": normalize_phone(verification_phone)}, order={"orderNo": order.get("name")})


async def get_tracking_for_order(order):
    order_no = str(order.get("name") or "").lstrip("#").strip()
    if not order_no:
        return None
    try:
        result = await get_ship_panel_tracking("order_no", order_no)
        return result if result.get("found") else None
    except Exception as exc:
        return {"success": False, "found": False, "message": str(exc), "tracking": None}


async def build_verified_order_response(order, verification_method):
    tracking_result = await get_tracking_for_order(order)
    summary = build_order_summary(order, tracking_result.get("tracking") if tracking_result else None)
    return build_response(True, True, "confirm_selected_order", summary["displayText"], verified=True, nextPrompt="Please select the issue for which you need support.", order=summary["order"], tracking=summary["tracking"], lookup={"verificationMethod": verification_method}, upstream={"shopify": {"found": True, "message": None}, "shipPanel": {"found": tracking_result.get("found"), "message": tracking_result.get("message")} if tracking_result else None})


def build_order_summary(order, ship_tracking):
    shopify_tracking = order.get("tracking", [None])[0] if order.get("tracking") else None
    awb = (ship_tracking or {}).get("awb") or (shopify_tracking or {}).get("number")
    courier = (ship_tracking or {}).get("courier") or (shopify_tracking or {}).get("company")
    tracking_url = (ship_tracking or {}).get("trackingUrl") or (shopify_tracking or {}).get("url")
    edd = ((ship_tracking or {}).get("orderInfo") or {}).get("edd")
    dispatch_status = (ship_tracking or {}).get("orderStatus") or order.get("fulfillmentStatus") or "Awaiting"
    payment_status = order.get("financialStatus") or "-"
    order_date = format_date(order.get("createdAt")) or ((ship_tracking or {}).get("orderInfo") or {}).get("orderDate")
    amount = format_amount(order.get("total"))
    return {
        "displayText": "\n".join([f"Order No: {order.get('name') or '-'}", f"Date: {order_date or '-'}", f"Total Amount: {amount or '-'}", f"Payment Status: {payment_status}"]),
        "order": {"id": order.get("id"), "orderNo": order.get("name"), "createdAt": order.get("createdAt"), "date": order_date, "amount": amount, "financialStatus": order.get("financialStatus"), "fulfillmentStatus": order.get("fulfillmentStatus"), "customer": order.get("customer"), "lineItems": order.get("lineItems") or []},
        "tracking": {"available": bool(awb), "dispatchStatus": dispatch_status, "courier": courier, "awb": awb, "trackingUrl": tracking_url, "edd": edd},
    }


def build_response(success, found, action, reply, **kwargs):
    return {"success": success, "flow": FLOW, "found": found, "verified": kwargs.get("verified"), "action": action, "missingInputs": kwargs.get("missingInputs", []), "reply": reply, "nextPrompt": kwargs.get("nextPrompt"), "message": kwargs.get("message"), "lookup": kwargs.get("lookup"), "order": kwargs.get("order"), "tracking": kwargs.get("tracking"), "upstream": kwargs.get("upstream")}


def format_date(value):
    if not value: return None
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return f"{date.day:02d}/{date.month:02d}/{date.year}"
    except ValueError:
        return str(value)
def format_amount(total): return f"{total.get('amount')}{' ' + total.get('currencyCode') if total.get('currencyCode') else ''}" if total and total.get("amount") else None
def get_order_phone_candidates(order): return [x for x in [normalize_phone((order.get("customer") or {}).get("phone")), normalize_phone((order.get("shippingAddress") or {}).get("phone"))] if x]
def phone_matches_any(phone, candidates): return bool(normalize_phone(phone) and normalize_phone(phone) in candidates)
