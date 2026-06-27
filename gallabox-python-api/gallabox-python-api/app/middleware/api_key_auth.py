import hmac

from fastapi import Header, HTTPException

from app.config import settings


async def require_external_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    if not settings.external_api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "External API access is not configured.",
                "code": "EXTERNAL_API_KEY_NOT_CONFIGURED",
            },
        )

    provided = x_api_key or ""
    if not provided and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = token

    if not provided:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Missing API key.",
                "code": "EXTERNAL_API_KEY_MISSING",
                "acceptedHeaders": ["x-api-key", "Authorization: Bearer <key>"],
            },
        )

    if not hmac.compare_digest(provided.strip(), settings.external_api_key):
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Invalid API key.",
                "code": "EXTERNAL_API_KEY_INVALID",
                "receivedKeyLength": len(provided.strip()),
                "configuredKeyLength": len(settings.external_api_key),
            },
        )
