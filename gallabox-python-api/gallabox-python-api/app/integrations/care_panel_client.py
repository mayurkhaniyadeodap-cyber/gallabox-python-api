from typing import Any

import httpx

from app.config import settings


async def fetch_tickets_by_phone(phone: str) -> dict[str, Any]:
    url = f"{settings.care_panel_base_url.rstrip('/')}/api/gallabox/tickets/{phone}"
    return await get_json(url)


async def fetch_ticket_detail(ticket_id: str) -> dict[str, Any]:
    url = f"{settings.care_panel_base_url.rstrip('/')}/api/gallabox/ticket/{ticket_id}"
    return await get_json(url)


async def get_json(url: str) -> dict[str, Any]:
    timeout = settings.care_panel_timeout_ms / 1000
    headers = {}
    if settings.care_panel_bearer_token:
        headers["Authorization"] = f"Bearer {settings.care_panel_bearer_token}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Care Panel request timed out while connecting to {url}.") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Care Panel request failed before response: {exc.__class__.__name__}.") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Care Panel request failed with status {response.status_code}.")

    try:
        return response.json()
    except ValueError as exc:
        content_type = response.headers.get("content-type", "")
        body_preview = response.text[:500]
        raise RuntimeError(
            f"Care Panel returned non-JSON response from {url}. "
            f"Status: {response.status_code}. Content-Type: {content_type}. Body: {body_preview}"
        ) from exc
    