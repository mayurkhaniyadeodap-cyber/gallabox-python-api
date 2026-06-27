from datetime import datetime, timedelta
import re
from typing import Any

from app.integrations.ship_panel_client import get_ship_panel_tracking
from app.services.common import has_value, parse_date, start_of_day

FLOW = "shipment_delivery_tracking"
TOPICS = {
    "shipment_status",
    "estimated_delivery_date",
    "delay_in_shipment",
    "expedite_delivery",
    "tracking_not_updating",
    "delivery_agent_attempt",
    "call_before_delivery",
    "reschedule_delivery",
    "contact_courier_partner",
    "track_order_via_app",
    "out_for_delivery_not_received",
    "marked_delivered_not_received",
    "shipment_showing_rto",
}

CARE_PANEL_ISSUES = {
    "shipment_status": {"id": 1, "name": "Shipment Tracking"},
    "estimated_delivery_date": {"id": 1, "name": "Shipment Tracking"},
    "tracking_not_updating": {"id": 1, "name": "Shipment Tracking"},
    "delay_in_shipment": {"id": 2, "name": "delivery delayed"},
    "marked_delivered_not_received": {"id": 3, "name": "order not received but shown as Delivered"},
    "expedite_delivery": {"id": 23, "name": "urgent delivery request"},
    "out_for_delivery_not_received": {"id": 13, "name": "order not received but shown as Out For Delivery"},
    "reschedule_delivery": {"id": 14, "name": "reschedule my delivery"},
    "shipment_showing_rto": {"id": 15, "name": "RTO"},
}


async def resolve_shipment_flow(input_data: dict[str, Any]) -> dict[str, Any]:
    topic = normalize_topic(input_data.get("topic"))
    if not topic:
        return build_decision(False, None, "await_customer_input", "Please select a valid shipment or delivery query type.", message="Invalid or missing shipment flow topic.", missingInputs=["topic"])

    if topic == "expedite_delivery":
        return build_decision(True, topic, "create_ticket", "Yes, our team will contact you soon.", ticketRequired=True)
    if topic == "call_before_delivery":
        return build_decision(True, topic, "info_only", "Most courier partners call before delivery, but this is not guaranteed. Please keep your registered phone number reachable on the expected delivery day.")
    if topic == "track_order_via_app":
        return build_decision(True, topic, "info_only", "Open the DeoDap app, go to My Orders, select the order, and tap Track Order to see live courier status.")
    if topic == "reschedule_delivery":
        return await resolve_reschedule_delivery(input_data, topic)
    if topic == "contact_courier_partner" and not wants_deodap_coordination(input_data):
        return build_decision(True, topic, "info_only", "The courier partner name and tracking ID are in your shipment Email/SMS. Please search the courier customer care number on their official website.")

    tracking_result = await resolve_tracking(input_data)
    tracking = tracking_result.get("tracking")
    if not tracking_result.get("found") or not tracking:
        return build_decision(True, topic, "await_customer_input" if topic == "contact_courier_partner" else "info_only", tracking_result.get("reply"), missingInputs=tracking_result.get("missingInputs", []), trackingResult=tracking_result)

    return decide_with_tracking(topic, input_data, tracking_result)


async def resolve_tracking(input_data: dict[str, Any]) -> dict[str, Any]:
    if not has_value(input_data.get("trackWith")) or not has_value(input_data.get("refNo")):
        return {"found": False, "missingInputs": ["trackWith", "refNo"], "reply": "Please share your Order ID, AWB, or registered mobile number so we can check the shipment status."}
    result = await get_ship_panel_tracking(input_data.get("trackWith"), input_data.get("refNo"))
    if not result.get("found"):
        result["missingInputs"] = []
        result["reply"] = "We could not find tracking details with the provided information. Please recheck the Order ID, AWB, or registered mobile number."
    return result


def decide_with_tracking(topic: str, input_data: dict[str, Any], tracking_result: dict[str, Any]) -> dict[str, Any]:
    tracking = tracking_result["tracking"]
    shipment = summarize_shipment(tracking)

    if not shipment["shipped"]:
        reply = tracking_link_reply(tracking) if topic == "shipment_status" else not_shipped_reply(topic)
        return build_decision(True, topic, "info_only", reply, trackingResult=tracking_result, shipment=shipment)

    if topic == "shipment_status":
        if shipment["eddBreached"]:
            return build_decision(True, topic, "create_ticket", f"{tracking_link_reply(tracking)} We are sorry for the delay. Your expected delivery date has passed, so our team will check with the courier and update you.", True, trackingResult=tracking_result, shipment=shipment)
        return build_decision(True, topic, "info_only", tracking_link_reply(tracking), trackingResult=tracking_result, shipment=shipment)

    if topic == "estimated_delivery_date":
        if not shipment["edd"]:
            return build_decision(True, topic, "info_only", f"Your shipment has been created with {'AWB ' + tracking['awb'] if tracking.get('awb') else 'tracking details'}, but the estimated delivery date is not available yet. Please check again shortly; EDD usually appears after the courier pickup scan is updated.", trackingResult=tracking_result, shipment=shipment)
        if shipment["eddBreached"]:
            return build_decision(True, topic, "create_ticket", f"{tracking_link_reply(tracking)} We are sorry for the delay. Our team will confirm the latest ETA with the courier and update you soon.", True, trackingResult=tracking_result, shipment=shipment)
        return build_decision(True, topic, "info_only", f"Your EDD is {shipment['edd']}. You will receive the parcel on or before this date. {tracking_link_reply(tracking)}", trackingResult=tracking_result, shipment=shipment)

    if topic == "delay_in_shipment":
        if shipment["pickupDelayed"]:
            return build_decision(True, topic, "create_ticket", f"We are sorry for the delay. Your shipment is with {tracking.get('courier') or 'the courier'}{f' under AWB {tracking.get('awb')}' if tracking.get('awb') else ''}, but pickup/update appears delayed. Our team will check this with the courier and update you soon.", True, trackingResult=tracking_result, shipment=shipment)
        if not shipment["edd"]:
            return build_decision(True, topic, "info_only", f"Your shipment is currently marked as {shipment.get('status') or 'in progress'}{f' with {tracking.get('courier')}' if tracking.get('courier') else ''}{f', AWB {tracking.get('awb')}' if tracking.get('awb') else ''}. The estimated delivery date is not available yet; it usually appears after courier pickup and transit scans are updated.", trackingResult=tracking_result, shipment=shipment)
        if shipment["eddBreached"]:
            return build_decision(True, topic, "create_ticket", f"{tracking_link_reply(tracking)} Our team will connect with you soon.", True, trackingResult=tracking_result, shipment=shipment)
        return build_decision(True, topic, "info_only", f"Your expected delivery date is {shipment['edd']}. You will receive the parcel on or before this date.", trackingResult=tracking_result, shipment=shipment)

    if topic == "tracking_not_updating":
        if shipment["orderAgeHours"] is not None and shipment["orderAgeHours"] <= 24:
            return build_decision(True, topic, "info_only", "Tracking updates may take 24 hours to reflect. Please check again shortly.", trackingResult=tracking_result, shipment=shipment)
        return build_decision(True, topic, "create_ticket", "We understand the tracking is not updating. Our team will check this with the courier and update you soon.", True, trackingResult=tracking_result, shipment=shipment)

    if topic == "delivery_agent_attempt":
        prefix = f"The delivery agent will attempt delivery on the estimated delivery date: {shipment['edd']}." if shipment["edd"] else "The delivery agent will attempt delivery on the estimated delivery date shown in your tracking link."
        return build_decision(True, topic, "info_only", f"{prefix} {tracking_link_reply(tracking)}", trackingResult=tracking_result, shipment=shipment)

    if topic == "contact_courier_partner":
        return build_decision(True, topic, "create_ticket", f"Please share your Order ID and we will coordinate on your behalf. Current courier: {tracking.get('courier') or 'not available'}. AWB: {tracking.get('awb') or 'not available'}.", True, trackingResult=tracking_result, shipment=shipment)

    if topic == "out_for_delivery_not_received":
        return decide_out_for_delivery(input_data, tracking, tracking_result, shipment, topic)

    if topic == "marked_delivered_not_received":
        return decide_marked_delivered(input_data, tracking, tracking_result, shipment, topic)

    if topic == "shipment_showing_rto":
        return decide_rto(input_data, tracking, tracking_result, shipment, topic)

    return build_decision(True, topic, "info_only", tracking_link_reply(tracking), trackingResult=tracking_result, shipment=shipment)


def decide_out_for_delivery(input_data, tracking, tracking_result, shipment, topic):
    if not shipment["outForDelivery"]:
        return build_decision(True, topic, "info_only", f"{tracking_link_reply(tracking)} The shipment is not currently marked as out for delivery.", trackingResult=tracking_result, shipment=shipment)
    if is_same_business_day(input_data, tracking):
        return build_decision(True, topic, "info_only", "Delivery can happen any time until end of business day. Please keep your phone reachable.", trackingResult=tracking_result, shipment=shipment)
    if shipment["outForDeliveryAgeHours"] is not None and shipment["outForDeliveryAgeHours"] <= 24:
        return build_decision(True, topic, "info_only", "Your order is marked as out for delivery. Delivery can take some time after the OFD scan, so please keep your phone reachable and wait until 24 hours from the out-for-delivery update.", trackingResult=tracking_result, shipment=shipment)
    return build_decision(True, topic, "create_ticket", "We understand the order is out for delivery but not received yet. Our team will escalate this to the courier and update you soon.", True, trackingResult=tracking_result, shipment=shipment)


def decide_marked_delivered(input_data, tracking, tracking_result, shipment, topic):
    if not shipment["delivered"]:
        return build_decision(True, topic, "info_only", f"{tracking_link_reply(tracking)} The shipment is not currently marked as delivered.", trackingResult=tracking_result, shipment=shipment)
    if shipment["deliveredAgeHours"] is not None and shipment["deliveredAgeHours"] > 48:
        return build_decision(True, topic, "create_ticket", "We understand your concern. The 48-hour courier escalation window after delivery status has passed, but our team will still try to coordinate with the courier on a best-effort basis.", True, trackingResult=tracking_result, shipment=shipment)
    if customer_still_concerned(input_data):
        return build_decision(True, topic, "create_ticket", "Share your Order ID within 48 hours of the Delivered status. We will raise a Proof of Delivery (POD) investigation with the courier.", True, trackingResult=tracking_result, shipment=shipment)
    return build_decision(True, topic, "info_only", "Please check with family, neighbours, or building security first, as parcels are sometimes handed over to them.", trackingResult=tracking_result, shipment=shipment)


def decide_rto(input_data, tracking, tracking_result, shipment, topic):
    if not shipment["rto"]:
        return build_decision(True, topic, "info_only", f"{tracking_link_reply(tracking)} The shipment is not currently showing RTO in tracking.", trackingResult=tracking_result, shipment=shipment)
    if is_courier_error(input_data):
        return build_decision(True, topic, "create_ticket", "We understand this may be a courier error. We will coordinate with the courier and offer a free re-ship if the shipment was returned despite the customer being reachable and no valid delivery attempt being made.", True, trackingResult=tracking_result, shipment=shipment)
    return build_decision(True, topic, "create_ticket", f"{tracking_link_reply(tracking)}\n\nRTO usually happens due to incorrect/incomplete address, phone unreachable, recipient unavailable after multiple attempts, or refused delivery. Our team will check and update.", True, trackingResult=tracking_result, shipment=shipment)


async def resolve_reschedule_delivery(input_data: dict[str, Any], topic: str):
    preferred = str(input_data.get("preferredDate") or "").strip()
    if not preferred:
        return build_decision(False, topic, "await_customer_input", "Please share the preferred delivery date in DD-MM-YYYY format.", message="Preferred delivery date is required.", missingInputs=["preferredDate"])
    preferred_date = parse_preferred_date(preferred)
    if not preferred_date:
        return build_decision(False, topic, "await_customer_input", "Please share a valid preferred delivery date in DD-MM-YYYY format.", message="Preferred delivery date format is invalid.", missingInputs=["preferredDate"], errors=[{"field": "preferredDate", "code": "INVALID_DATE_FORMAT", "expectedFormat": "DD-MM-YYYY"}])
    if not has_value(input_data.get("trackWith")) or not has_value(input_data.get("refNo")):
        return build_decision(False, topic, "await_customer_input", "Please share your Order ID, AWB, or registered mobile number so we can check the estimated delivery date before rescheduling.", message="Order lookup details are required before rescheduling delivery.", missingInputs=["trackWith", "refNo"])

    tracking_result = await resolve_tracking(input_data)
    tracking = tracking_result.get("tracking")
    if not tracking_result.get("found") or not tracking:
        return build_decision(False, topic, "await_customer_input", tracking_result.get("reply") or "We could not find tracking details with the provided information. Please recheck the Order ID, AWB, or registered mobile number.", message="Shipment lookup failed.", missingInputs=tracking_result.get("missingInputs", []), trackingResult=tracking_result)

    shipment = summarize_shipment(tracking)
    edd_date = parse_date((tracking.get("orderInfo") or {}).get("edd"))
    if not edd_date:
        return build_decision(False, topic, "await_customer_input", "Estimated delivery date is not available yet, so we cannot reschedule this delivery right now. Please check again after the courier updates the EDD.", message="Estimated delivery date is required before rescheduling delivery.", trackingResult=tracking_result, shipment=shipment)

    validation = validate_preferred_date_window(preferred_date, edd_date)
    if not validation["valid"]:
        reply = validation.get("reply") or f"Please share a preferred delivery date between {validation['startDisplay']} and {validation['endDisplay']}."
        return build_decision(False, topic, "await_customer_input", reply, message=validation["message"], missingInputs=["preferredDate"], errors=[{"field": "preferredDate", "code": validation["code"], "allowedFrom": validation["startDisplay"], "allowedTo": validation["endDisplay"]}], trackingResult=tracking_result, shipment=shipment)

    return build_decision(True, topic, "create_ticket", f"Yes, you can reschedule. We have logged your preferred date: {preferred}.", True, trackingResult=tracking_result, shipment=shipment)


def summarize_shipment(tracking: dict[str, Any]):
    edd = (tracking.get("orderInfo") or {}).get("edd")
    order_date = (tracking.get("orderInfo") or {}).get("orderDate")
    edd_date = parse_date(edd)
    order_date_value = parse_date(order_date)
    latest_scan = tracking.get("scans", [None])[0] if tracking.get("scans") else None
    ofd_scan = find_out_for_delivery_scan(tracking)
    ofd_date = parse_date(ofd_scan.get("scannedAt") if ofd_scan else None)
    delivered_scan = find_delivered_scan(tracking)
    delivered_date = parse_date(delivered_scan.get("scannedAt") if delivered_scan else None)
    rto_scan = find_rto_scan(tracking)
    now = datetime.now()
    return {
        "shipped": bool(tracking.get("awb")),
        "awb": tracking.get("awb"),
        "courier": tracking.get("courier"),
        "status": tracking.get("orderStatus") or (latest_scan or {}).get("message"),
        "edd": edd,
        "eddBreached": start_of_day(now) > start_of_day(edd_date) if edd_date else False,
        "orderDate": order_date,
        "orderAgeHours": int((now - order_date_value).total_seconds() // 3600) if order_date_value else None,
        "latestScan": latest_scan,
        "outForDelivery": bool(ofd_scan),
        "outForDeliveryAgeHours": int((now - ofd_date).total_seconds() // 3600) if ofd_date else None,
        "delivered": bool(delivered_scan),
        "deliveredAgeHours": int((now - delivered_date).total_seconds() // 3600) if delivered_date else None,
        "rto": bool(rto_scan),
        "rtoScan": rto_scan,
        "pickupDelayed": has_pickup_delay_issue(tracking),
    }


def tracking_link_reply(tracking: dict[str, Any]) -> str:
    info = tracking.get("orderInfo") or {}
    order_no = tracking.get("orderNo") or info.get("orderNo") or "-"
    order_date = info.get("orderDate") or "-"
    status = tracking.get("orderStatus") or "Awaiting"
    if not tracking.get("awb"):
        return "\n".join([f"DeoDap Order No: {order_no}", f"Date: {order_date}", f"Dispatch Status: {status}", "Courier Details Awaited.", "", "Generally it takes up to 24 hours before we upload the tracking details.", "You can check back again to see updated tracking info."])
    return "\n".join([f"Order No: {order_no}", f"Date: {order_date}", f"Dispatch Status: {status}", f"Courier Company: {tracking.get('courier') or '-'}", "Courier Contact No: Please refer to the courier official website.", f"Courier Tracking ID: {tracking.get('awb')}", f"Tracking URL: {tracking.get('trackingUrl') or '-'}", f"Estimated Delivery Date: {info.get('edd') or '-'}"])


def not_shipped_reply(topic):
    if topic == "delay_in_shipment":
        return "Due to a manpower issue there is a slight delay. We will ship your order as soon as possible."
    if topic == "estimated_delivery_date":
        return "Once shipped, you will receive tracking number and EDD via Email/SMS."
    return "Your order is being prepared. Once shipped, you will receive a tracking number and link via Email/SMS. You can check live status there."


def build_decision(success, topic, action, reply, ticketRequired=False, **kwargs):
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
        "missingInputs": kwargs.get("missingInputs", []),
        "errors": kwargs.get("errors", []),
        "reply": reply,
        "message": kwargs.get("message"),
        "shipment": kwargs.get("shipment"),
        "tracking": tracking_result.get("tracking") if tracking_result else None,
        "upstream": {"success": tracking_result.get("success"), "found": tracking_result.get("found"), "message": tracking_result.get("message")} if tracking_result else None,
    }


def normalize_topic(topic): return topic if str(topic or "").strip().lower() in TOPICS else ""
def wants_deodap_coordination(data): return data.get("wantsDeodapToCoordinate") is True or data.get("coordinateWithCourier") is True
def customer_still_concerned(data): return data.get("stillNotLocated") is True or data.get("customerReturned") is True or data.get("raisePodInvestigation") is True
def is_courier_error(data): return data.get("courierError") is True or data.get("customerReachableNoAttempt") is True or data.get("noDeliveryAttemptMade") is True
def parse_preferred_date(value):
    match = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", str(value or "").strip())
    if not match:
        return None
    try:
        return datetime(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        return None
def validate_preferred_date_window(preferred_date, edd_date):
    today = start_of_day(datetime.now())
    edd_start = start_of_day(edd_date)
    start_date = edd_start if edd_start > today else today
    end_date = edd_start + timedelta(days=4)
    preferred_start = start_of_day(preferred_date)
    start_display = format_date_for_reply(start_date)
    end_display = format_date_for_reply(end_date)
    if today > end_date:
        return {"valid": False, "code": "EDD_RESCHEDULE_WINDOW_EXPIRED", "message": "The allowed reschedule window from estimated delivery date has already passed.", "reply": f"The reschedule window for this shipment has already passed. Preferred delivery date can only be within 4 days from the estimated delivery date ({format_date_for_reply(edd_start)} to {end_display}).", "startDisplay": format_date_for_reply(edd_start), "endDisplay": end_display}
    if preferred_start < start_date:
        return {"valid": False, "code": "PREFERRED_DATE_TOO_EARLY", "message": "Preferred delivery date is before the allowed reschedule window.", "startDisplay": start_display, "endDisplay": end_display}
    if preferred_start > end_date:
        return {"valid": False, "code": "PREFERRED_DATE_TOO_LATE", "message": "Preferred delivery date is outside the next 4 days from estimated delivery date.", "startDisplay": start_display, "endDisplay": end_display}
    return {"valid": True, "startDisplay": start_display, "endDisplay": end_display}
def format_date_for_reply(date): return date.strftime("%d-%m-%Y")
def status_text(tracking): return " ".join([str(tracking.get("orderStatus") or ""), *[str(s.get("message") or "") for s in tracking.get("scans", [])]]).lower()
def find_out_for_delivery_scan(tracking): return next((s for s in tracking.get("scans", []) if "out for delivery" in str(s.get("message") or "").lower()), None)
def find_delivered_scan(tracking):
    if "delivered" in str(tracking.get("orderStatus") or "").lower():
        return tracking.get("scans", [{}])[0] if tracking.get("scans") else {"scannedAt": None}
    return next((s for s in tracking.get("scans", []) if "delivered" in str(s.get("message") or "").lower() and "out for delivery" not in str(s.get("message") or "").lower()), None)
def find_rto_scan(tracking):
    if has_rto_text(tracking.get("orderStatus")):
        return tracking.get("scans", [{}])[0] if tracking.get("scans") else {"scannedAt": None, "message": tracking.get("orderStatus")}
    return next((s for s in tracking.get("scans", []) if has_rto_text(s.get("message"))), None)
def has_rto_text(value):
    text = str(value or "").lower()
    return "rto" in text or "return to origin" in text or "returned to origin" in text or "returning to origin" in text
def has_pickup_delay_issue(tracking):
    text = status_text(tracking)
    return any(term in text for term in ["failed to pickup", "failed to pick", "not ready for pickup", "could not attempted", "pickup to be attend"])
def is_same_business_day(input_data, tracking):
    if isinstance(input_data.get("sameBusinessDay"), bool):
        return input_data["sameBusinessDay"]
    scan = find_out_for_delivery_scan(tracking)
    date = parse_date(scan.get("scannedAt") if scan else None)
    return bool(date and start_of_day(date) == start_of_day(datetime.now()))
