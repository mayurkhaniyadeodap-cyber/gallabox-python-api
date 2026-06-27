import asyncio
from typing import Any

from app.integrations.care_panel_client import fetch_ticket_detail, fetch_tickets_by_phone
from app.services.common import has_value, normalize_phone


async def get_open_tickets_for_customer(input_data: dict[str, Any]) -> dict[str, Any]:
    phone = normalize_phone(input_data.get("phone") or input_data.get("customerPhone"))
    if not phone:
        return {
            "success": False,
            "action": "await_customer_phone",
            "message": "Customer phone is required.",
            "missingInputs": ["phone"],
            "tickets": [],
            "ticketCount": 0,
        }

    issue_filter = normalize_issue_filter(input_data.get("issueIds") or input_data.get("issueId") or input_data.get("issues"))
    list_response = await fetch_tickets_by_phone(phone)
    listed_tickets = list_response.get("data") if isinstance(list_response.get("data"), list) else []

    open_tickets = [
        ticket for ticket in listed_tickets
        if is_open_ticket(ticket) and issue_matches(ticket, issue_filter)
    ]

    detail_results = await asyncio.gather(
        *[fetch_ticket_detail(str(ticket.get("id"))) for ticket in open_tickets if has_value(ticket.get("id"))],
        return_exceptions=True,
    )

    detailed_tickets = []
    detail_errors = []
    for ticket, result in zip(open_tickets, detail_results):
        if isinstance(result, Exception):
            detail_errors.append({
                "ticketId": ticket.get("id"),
                "message": str(result) or result.__class__.__name__,
                "errorType": result.__class__.__name__,
            })
            detailed_tickets.append(normalize_ticket_summary(ticket))
            continue

        detail = result.get("data") or {}
        detailed_tickets.append(normalize_ticket_detail(detail, fallback=ticket))

    return {
        "success": True,
        "action": "show_open_tickets" if detailed_tickets else "no_open_tickets",
        "reply": build_reply(detailed_tickets),
        "phone": phone,
        "issueFilter": issue_filter if issue_filter == "all" else sorted(issue_filter),
        "ticketCount": len(detailed_tickets),
        "hasTickets": bool(detailed_tickets),
        "tickets": detailed_tickets,
        "detailErrors": detail_errors,
        "upstream": {
            "listStatus": list_response.get("status"),
            "listMessage": list_response.get("message"),
            "totalTicketsFromCarePanel": len(listed_tickets),
        },
    }


def build_reply(tickets: list[dict[str, Any]]) -> str:
    if not tickets:
        return "No open ticket found for this issue. You can continue creating a new support ticket."

    lines = [
        "You already have open ticket(s) for this issue. Please check the details below:"
    ]

    for index, ticket in enumerate(tickets, start=1):
        lines.extend([
            "",
            f"{index}. Ticket: {ticket.get('ticketNumber') or '-'}",
            f"Issue: {ticket.get('issue') or '-'}",
            f"Status: {ticket.get('status') or '-'}",
            f"Created: {ticket.get('createdAt') or '-'}",
            f"Order No: {ticket.get('shopifyOrderNo') or '-'}",
            f"URL: {ticket.get('url') or '-'}"
        ])

    return "\n".join(lines)


def normalize_issue_filter(value: Any):
    if value is None or str(value).strip().lower() == "all":
        return "all"

    raw_values = value if isinstance(value, list) else str(value).split(",")
    issue_ids = set()
    for item in raw_values:
        try:
            issue_ids.add(int(str(item).strip()))
        except ValueError:
            continue
    return issue_ids or "all"


def is_open_ticket(ticket: dict[str, Any]) -> bool:
    return str(ticket.get("status") or "").strip().lower() not in {"closed", "resolved", "cancelled", "canceled"}


def issue_matches(ticket: dict[str, Any], issue_filter) -> bool:
    if issue_filter == "all":
        return True
    try:
        return int(ticket.get("issue_id")) in issue_filter
    except (TypeError, ValueError):
        return False


def normalize_ticket_summary(ticket: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ticket.get("id"),
        "ticketNumber": ticket.get("ticket_number"),
        "status": ticket.get("status"),
        "issueId": ticket.get("issue_id"),
        "issue": ticket.get("issue"),
        "shopifyOrderNo": ticket.get("shopify_order_no"),
        "createdAt": ticket.get("created_at"),
        "url": ticket.get("url"),
        "detailLoaded": False,
    }


def normalize_ticket_detail(detail: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": detail.get("id") or fallback.get("id"),
        "ticketNumber": detail.get("ticket_number") or fallback.get("ticket_number"),
        "name": detail.get("name"),
        "phone": detail.get("phone"),
        "email": detail.get("email"),
        "status": detail.get("status") or fallback.get("status"),
        "issueId": detail.get("issue_id") or fallback.get("issue_id"),
        "issue": detail.get("issue") or fallback.get("issue"),
        "shopifyOrderNo": detail.get("shopify_order_no") or fallback.get("shopify_order_no"),
        "createdAt": detail.get("created") or fallback.get("created_at"),
        "url": fallback.get("url") or detail.get("url"),
        "totalComments": detail.get("total_comments", 0),
        "comments": detail.get("comments") or [],
        "detailLoaded": True,
    }
