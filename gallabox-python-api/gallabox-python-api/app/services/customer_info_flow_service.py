import re
from typing import Any

from app.integrations.ship_panel_client import get_ship_panel_tracking
from app.services.common import has_value

FLOW = "delivery_address_customer_info_changes"
TOPICS = {"change_address_pincode", "change_address_phone", "update_gstin_after_order"}
ADDRESS_CHANGE_TOPICS = {"change_address_pincode", "change_address_phone"}
CARE_PANEL_ISSUES = {
    "change_address_pincode": {"id": 4, "name": "Adress/Phoneno change"},
    "change_address_phone": {"id": 4, "name": "Adress/Phoneno change"},
}


async def resolve_customer_info_flow(input_data: dict[str, Any]) -> dict[str, Any]:
    topic = normalize_topic(input_data.get("topic"))
    if not topic:
        return build_decision(False, None, "await_customer_input", "Please select a valid address or customer information query type.", message="Invalid or missing customer info flow topic.", missingInputs=["topic"])
    if topic in ADDRESS_CHANGE_TOPICS:
        return await resolve_address_pincode_change(input_data, topic)
    if topic == "update_gstin_after_order":
        return resolve_gstin_update(input_data, topic)
    return build_decision(False, topic, "await_customer_input", "Please select a valid address or customer information query type.", missingInputs=["topic"])


async def resolve_address_pincode_change(input_data: dict[str, Any], topic: str) -> dict[str, Any]:
    if not has_value(input_data.get("trackWith")) or not has_value(input_data.get("refNo")):
        return build_decision(False, topic, "await_customer_input", "Please share your Order ID, AWB, or registered mobile number so we can check whether your order has shipped.", message="Order lookup details are required before address or pincode change.", missingInputs=["trackWith", "refNo"])

    tracking_result = await get_ship_panel_tracking(input_data.get("trackWith"), input_data.get("refNo"))
    if not tracking_result.get("found") or not tracking_result.get("tracking"):
        return build_decision(False, topic, "await_customer_input", "We could not find shipment details with the provided information. Please recheck the Order ID, AWB, or registered mobile number.", message="Shipment lookup failed.", trackingResult=tracking_result)

    shipment = summarize_shipment(tracking_result["tracking"])
    new_pincode = input_data.get("newPincode")
    has_requested_change = has_value(input_data.get("newAddress")) or has_value(new_pincode)

    if has_value(new_pincode) and not is_valid_pincode(new_pincode):
        return build_decision(False, topic, "await_customer_input", "Please share a valid 6-digit pincode.", message="Pincode format is invalid.", missingInputs=["newPincode"], errors=[{"field": "newPincode", "code": "INVALID_PINCODE_FORMAT"}], shipment=shipment, trackingResult=tracking_result)

    if not has_requested_change:
        if not shipment["shipped"]:
            return build_decision(False, topic, "await_customer_input", "Your order has not shipped yet. Please share the full new delivery address and/or new pincode you want to update.", updateAllowed=True, message="New address or pincode is required.", missingInputs=["newAddressOrPincode"], shipment=shipment, trackingResult=tracking_result)
        return build_decision(False, topic, "await_customer_input", "Yes, please share the details. Since your order is already shipped, pincode changes may not be possible; usually only the address can be changed within the same pincode. Our team will coordinate with the courier.", ticketRequired=True, message="New address or pincode is required.", missingInputs=["newAddressOrPincode"], shipment=shipment, trackingResult=tracking_result)

    if not shipment["shipped"]:
        return build_decision(True, topic, "update_in_system", "Your order has not shipped yet. We can update the full delivery address and/or pincode as per the details shared.", updateAllowed=True, shipment=shipment, trackingResult=tracking_result, collectedInputs=collect_address_pincode_inputs(input_data))

    return build_decision(True, topic, "create_ticket", "We have received your updated address/pincode details. Since your order is already shipped, pincode changes may not be possible. Our team will create a ticket and coordinate with the courier.", ticketRequired=True, shipment=shipment, trackingResult=tracking_result, collectedInputs=collect_address_pincode_inputs(input_data))


def resolve_gstin_update(input_data: dict[str, Any], topic: str) -> dict[str, Any]:
    stage = normalize_stage(input_data.get("stage"))
    if not stage:
        return build_decision(False, topic, "await_customer_input", "Please confirm whether the order is before checkout or already placed.", message="Order stage is required for GSTIN update.", missingInputs=["stage"])
    if stage == "before_checkout":
        return build_decision(True, topic, "info_only", "Add your GSTIN at checkout for it to reflect on the invoice.")
    if not has_value(input_data.get("gstin")):
        return build_decision(False, topic, "await_customer_input", "Please share your GSTIN number.", message="GSTIN number is required.", missingInputs=["gstin"])
    gstin = str(input_data.get("gstin")).strip().upper()
    if not is_valid_gstin(gstin):
        return build_decision(False, topic, "await_customer_input", "Please share a valid 15-character GSTIN number.", message="GSTIN number format is invalid.", missingInputs=["gstin"], errors=[{"field": "gstin", "code": "INVALID_GSTIN_FORMAT"}])
    return build_decision(True, topic, "create_ticket", "We do not provide GSTIN updates after order confirmation. Our team will review your request and update you.", ticketRequired=True, collectedInputs={"gstin": gstin})


def build_decision(success, topic, action, reply, ticketRequired=False, updateAllowed=False, **kwargs):
    issue = CARE_PANEL_ISSUES.get(topic or "")
    tracking_result = kwargs.get("trackingResult")
    return {
        "success": success,
        "flow": FLOW,
        "topic": topic,
        "issueId": issue.get("id") if issue else None,
        "issueName": issue.get("name") if issue else None,
        "action": action,
        "ticketRequired": ticketRequired,
        "updateAllowed": updateAllowed,
        "missingInputs": kwargs.get("missingInputs", []),
        "errors": kwargs.get("errors", []),
        "reply": reply,
        "message": kwargs.get("message"),
        "shipment": kwargs.get("shipment"),
        "tracking": tracking_result.get("tracking") if tracking_result else None,
        "collectedInputs": kwargs.get("collectedInputs"),
        "upstream": {"success": tracking_result.get("success"), "found": tracking_result.get("found"), "message": tracking_result.get("message")} if tracking_result else None,
    }


def summarize_shipment(tracking): return {"shipped": bool(tracking.get("awb")), "awb": tracking.get("awb"), "courier": tracking.get("courier"), "status": tracking.get("orderStatus"), "trackingUrl": tracking.get("trackingUrl")}
def collect_address_pincode_inputs(data): return {"newAddress": str(data.get("newAddress")).strip() if has_value(data.get("newAddress")) else None, "newPincode": str(data.get("newPincode")).strip() if has_value(data.get("newPincode")) else None}
def is_valid_pincode(pincode): return bool(re.match(r"^[1-9][0-9]{5}$", str(pincode or "").strip()))
def normalize_topic(topic): return str(topic or "").strip().lower() if str(topic or "").strip().lower() in TOPICS else ""
def normalize_stage(stage):
    normalized = str(stage or "").strip().lower()
    if normalized in {"before_checkout", "before checkout", "checkout"}:
        return "before_checkout"
    if normalized in {"after_order_placed", "after order placed", "after_order", "order_placed", "placed"}:
        return "after_order_placed"
    return ""
def is_valid_gstin(gstin): return bool(re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", gstin))
