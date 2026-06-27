from typing import Any

from app.services.care_panel_ticket_service import get_open_tickets_for_customer


async def attach_existing_ticket_if_any(result: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
    if not should_check_existing_ticket(result):
        return result

    phone = (
        input_data.get("phone")
        or input_data.get("customerPhone")
        or input_data.get("contactPhone")
        or input_data.get("mobile")
        or input_data.get("customerMobile")
    )

    if not phone or not result.get("issueId"):
        return {
            **result,
            "existingTicketFound": False,
            "carePanelTicketCheck": {
                "performed": False,
                "reason": "phone_missing" if not phone else "issue_id_missing",
            },
        }

    try:
        existing_ticket_result = await get_open_tickets_for_customer({
            "phone": phone,
            "issueIds": [result.get("issueId")],
        })
    except Exception as exc:
        return {
            **result,
            "existingTicketFound": False,
            "carePanelTicketCheck": {
                "performed": False,
                "error": {
                    "message": str(exc) or "Existing ticket check failed.",
                    "errorType": exc.__class__.__name__,
                },
            },
        }

    if not existing_ticket_result.get("hasTickets"):
        return {
            **result,
            "existingTicketFound": False,
            "carePanelTicketCheck": {
                "performed": True,
                "hasTickets": False,
                "ticketCount": 0,
            },
        }

    return {
        **result,
        "action": "show_open_tickets",
        "originalAction": result.get("action"),
        "ticketRequired": False,
        "existingTicketFound": True,
        "existingTicketCount": existing_ticket_result.get("ticketCount"),
        "existingTickets": existing_ticket_result.get("tickets"),
        "originalReply": result.get("reply"),
        "reply": existing_ticket_result.get("reply"),
        "carePanelTicketCheck": {
            "performed": True,
            "hasTickets": True,
            "ticketCount": existing_ticket_result.get("ticketCount"),
        },
    }


def should_check_existing_ticket(result: dict[str, Any] | None) -> bool:
    return bool(
        result
        and result.get("success") is not False
        and result.get("ticketRequired") is True
        and result.get("issueId")
    )
