from typing import Any, Callable

import httpx
from pymongo.errors import PyMongoError

from app.config import settings
from app.integrations.mongo import db

ORDER_FIELDS = """
id
name
createdAt
cancelledAt
closedAt
displayFinancialStatus
displayFulfillmentStatus
email
phone
tags
customer {
  id
  displayName
  email
  phone
}
shippingAddress {
  name
  phone
  city
  province
  country
  zip
}
totalPriceSet {
  shopMoney {
    amount
    currencyCode
  }
}
lineItems(first: 25) {
  nodes {
    name
    quantity
    sku
    variantTitle
    product {
      id
      title
      handle
      tags
    }
  }
}
fulfillments(first: 10) {
  status
  createdAt
  updatedAt
  trackingInfo(first: 5) {
    company
    number
    url
  }
}
"""

ORDER_LOOKUP_QUERY = f"""
query OrderLookup($query: String!) {{
  orders(first: 5, query: $query, sortKey: CREATED_AT, reverse: true) {{
    nodes {{
      {ORDER_FIELDS}
    }}
  }}
}}
"""

ORDER_IDS_BY_PHONE_QUERY = """
query OrderIdsByPhone($query: String!) {
  orders(first: 5, query: $query, sortKey: CREATED_AT, reverse: true) {
    nodes {
      id
      name
      createdAt
    }
  }
}
"""

CUSTOMER_ORDER_LOOKUP_QUERY = f"""
query CustomerOrderLookup($query: String!) {{
  customers(first: 5, query: $query) {{
    nodes {{
      id
      displayName
      email
      phone
      defaultAddress {{
        phone
      }}
      orders(first: 5, sortKey: CREATED_AT, reverse: true) {{
        nodes {{
          {ORDER_FIELDS}
        }}
      }}
    }}
  }}
}}
"""


async def find_shopify_order_by_order_id(order_id: str | None) -> dict[str, Any]:
    if not settings.shopify_enabled:
        return {"enabled": False, "found": False, "reason": "Shopify integration is disabled."}
    assert_shopify_config()

    normalized_order_id = normalize_order_id(order_id)
    query = build_order_search_query(normalized_order_id)
    order = await find_best_matching_order(
        query,
        lambda candidate: order_name_matches(candidate, normalized_order_id),
        allow_fallback=True,
    )

    if not order:
        return {
            "enabled": True,
            "found": False,
            "orderId": normalized_order_id,
            "reason": "No Shopify order matched this order ID.",
        }

    return {"enabled": True, "found": True, "order": sanitize_order(order)}


async def find_shopify_order_by_customer_contact(email: str | None = "", phone: str | None = "") -> dict[str, Any]:
    if not settings.shopify_enabled:
        return {"enabled": False, "found": False, "reason": "Shopify integration is disabled."}
    assert_shopify_config()

    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone)
    query_parts: list[str] = []
    if normalized_email:
        query_parts.append(f"email:{normalized_email}")
    if normalized_phone:
        query_parts.append(f"phone:{normalized_phone}")
        query_parts.append(f"phone:+91{normalized_phone}")

    if not query_parts:
        return {"enabled": True, "found": False, "reason": "No email or phone was available for Shopify customer lookup."}

    order = await find_best_matching_order(
        " OR ".join(query_parts),
        lambda candidate: contact_matches(candidate, normalized_email, normalized_phone),
        allow_fallback=False,
    )

    if not order:
        order = await find_latest_order_by_customer_search(normalized_email, normalized_phone)

    if not order:
        return {
            "enabled": True,
            "found": False,
            "email": normalized_email or None,
            "phone": normalized_phone or None,
            "reason": "No Shopify order matched the provided customer contact details.",
        }

    return {"enabled": True, "found": True, "lookupType": "customer_contact", "order": sanitize_order(order)}


async def find_shopify_order_ids_by_phone(phone: str | None) -> dict[str, Any]:
    if not settings.shopify_enabled:
        return {"enabled": False, "found": False, "orders": [], "reason": "Shopify integration is disabled."}
    assert_shopify_config()

    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return {"enabled": True, "found": False, "phone": None, "count": 0, "orders": [], "reason": "Phone is required."}

    query = f"phone:{normalized_phone} OR phone:+91{normalized_phone}"
    data = await shopify_graphql(ORDER_IDS_BY_PHONE_QUERY, {"query": query})
    nodes = ((data.get("orders") or {}).get("nodes")) or []

    if not nodes:
        customer_data = await shopify_graphql(CUSTOMER_ORDER_LOOKUP_QUERY, {"query": query})
        for customer in ((customer_data.get("customers") or {}).get("nodes")) or []:
            candidate_phones = [
                normalize_phone(customer.get("phone")),
                normalize_phone((customer.get("defaultAddress") or {}).get("phone")),
            ]
            if normalized_phone in candidate_phones:
                nodes = ((customer.get("orders") or {}).get("nodes")) or []
                break

    orders = [
        {"id": order.get("id"), "orderNo": order.get("name"), "createdAt": order.get("createdAt")}
        for order in nodes[:5]
    ]
    return {
        "enabled": True,
        "found": bool(orders),
        "phone": normalized_phone,
        "count": len(orders),
        "orders": orders,
    }


async def get_shopify_order_refund_details(order_id: str | None) -> dict[str, Any]:
    if not settings.shopify_enabled:
        return {"enabled": False, "found": False, "reason": "Shopify integration is disabled."}
    assert_shopify_config()

    order_result = await find_shopify_order_by_order_id(order_id)
    if not order_result.get("found") or not order_result.get("order"):
        return {
            "enabled": True,
            "found": False,
            "orderId": normalize_order_id(order_id),
            "reason": order_result.get("reason") or "No Shopify order matched this order ID.",
        }

    order = order_result["order"]
    rest_order = await fetch_shopify_rest_order(order.get("id"))
    refund_details = normalize_refund_details(rest_order, order)

    return {
        "enabled": True,
        "found": True,
        "orderId": normalize_order_id(order_id),
        "order": {
            "id": order.get("id"),
            "name": order.get("name"),
            "createdAt": order.get("createdAt"),
        },
        **refund_details,
    }


async def shopify_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    timeout = settings.shopify_timeout_ms / 1000
    access_token = await get_access_token()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                get_shopify_graphql_url(),
                headers={
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": access_token,
                },
                json={"query": query, "variables": variables},
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Shopify API request timed out while connecting to {get_shopify_graphql_url()}.") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Shopify API request failed before response: {exc.__class__.__name__}.") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Shopify API request failed with status {response.status_code}.")

    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify API returned {len(payload['errors'])} error(s).")
    return payload.get("data") or {}


async def shopify_rest(path: str) -> dict[str, Any]:
    timeout = settings.shopify_timeout_ms / 1000
    access_token = await get_access_token()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                get_shopify_rest_url(path),
                headers={
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": access_token,
                },
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Shopify REST API request timed out while connecting to {get_shopify_rest_url(path)}.") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Shopify REST API request failed before response: {exc.__class__.__name__}.") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Shopify REST API request failed with status {response.status_code}.")

    return response.json()


async def fetch_shopify_rest_order(order_gid: str | None) -> dict[str, Any]:
    numeric_order_id = get_numeric_order_id(order_gid)
    if not numeric_order_id:
        raise RuntimeError("Unable to determine Shopify numeric order ID for refund lookup.")
    payload = await shopify_rest(f"orders/{numeric_order_id}.json")
    return payload.get("order") or {}


async def find_best_matching_order(query: str, matcher: Callable[[dict[str, Any]], bool], allow_fallback: bool = False):
    data = await shopify_graphql(ORDER_LOOKUP_QUERY, {"query": query})
    orders = ((data.get("orders") or {}).get("nodes")) or []
    for order in orders:
        if matcher(order):
            return order
    return orders[0] if allow_fallback and orders else None


async def find_latest_order_by_customer_search(email: str, phone: str):
    query_parts = []
    if email:
        query_parts.append(f"email:{email}")
    if phone:
        query_parts.append(f"phone:{phone}")
        query_parts.append(f"phone:+91{phone}")
    if not query_parts:
        return None

    data = await shopify_graphql(CUSTOMER_ORDER_LOOKUP_QUERY, {"query": " OR ".join(query_parts)})
    customers = ((data.get("customers") or {}).get("nodes")) or []
    for customer in customers:
        candidate_emails = [normalize_email(customer.get("email"))]
        candidate_phones = [
            normalize_phone(customer.get("phone")),
            normalize_phone((customer.get("defaultAddress") or {}).get("phone")),
        ]
        if (email and email in candidate_emails) or (phone and phone in candidate_phones):
            orders = ((customer.get("orders") or {}).get("nodes")) or []
            return orders[0] if orders else None
    return None


def sanitize_order(order: dict[str, Any]) -> dict[str, Any]:
    tracking = []
    for fulfillment in order.get("fulfillments") or []:
        for item in fulfillment.get("trackingInfo") or []:
            tracking.append({"company": item.get("company"), "number": item.get("number"), "url": item.get("url")})

    customer = order.get("customer") or {}
    shipping = order.get("shippingAddress")
    total = (((order.get("totalPriceSet") or {}).get("shopMoney")) or {})
    line_items = ((order.get("lineItems") or {}).get("nodes")) or []

    return {
        "id": order.get("id"),
        "name": order.get("name"),
        "createdAt": order.get("createdAt"),
        "cancelledAt": order.get("cancelledAt"),
        "closedAt": order.get("closedAt"),
        "financialStatus": order.get("displayFinancialStatus"),
        "fulfillmentStatus": order.get("displayFulfillmentStatus"),
        "customer": {
            "id": customer.get("id"),
            "displayName": customer.get("displayName"),
            "email": customer.get("email") or order.get("email"),
            "phone": customer.get("phone") or order.get("phone"),
        },
        "shippingAddress": {
            "name": shipping.get("name"),
            "phone": shipping.get("phone"),
            "city": shipping.get("city"),
            "province": shipping.get("province"),
            "country": shipping.get("country"),
            "zip": shipping.get("zip"),
        } if shipping else None,
        "total": {"amount": total.get("amount"), "currencyCode": total.get("currencyCode")},
        "tags": order.get("tags") or [],
        "lineItems": [
            {
                "name": item.get("name"),
                "quantity": item.get("quantity"),
                "sku": item.get("sku"),
                "variantTitle": item.get("variantTitle"),
                "productTitle": (item.get("product") or {}).get("title"),
                "productHandle": (item.get("product") or {}).get("handle"),
                "productTags": (item.get("product") or {}).get("tags") or [],
            }
            for item in line_items
        ],
        "fulfillments": [
            {"status": f.get("status"), "createdAt": f.get("createdAt"), "updatedAt": f.get("updatedAt")}
            for f in order.get("fulfillments") or []
        ],
        "tracking": tracking,
    }


def assert_shopify_config():
    if not settings.shopify_shop_domain:
        raise RuntimeError("Shopify configuration is incomplete. Please set SHOPIFY_SHOP_DOMAIN.")
    if settings.shopify_auth_mode == "oauth":
        if not settings.shopify_client_id or not settings.shopify_client_secret:
            raise RuntimeError("Shopify OAuth configuration is incomplete.")
        return
    if not settings.shopify_admin_access_token:
        raise RuntimeError("Shopify token configuration is incomplete. Please set SHOPIFY_ADMIN_ACCESS_TOKEN.")


async def get_access_token() -> str:
    if settings.shopify_auth_mode == "oauth":
        token = await get_stored_shopify_access_token()
        if not token:
            raise RuntimeError("Shopify OAuth token is not installed. Complete OAuth install from the Node app first.")
        return token
    return settings.shopify_admin_access_token


async def get_stored_shopify_access_token() -> str | None:
    shop = normalize_shop(settings.shopify_shop_domain)
    try:
        token_record = await db.shopify_tokens.find_one({"shop": shop})
    except PyMongoError as exc:
        raise RuntimeError(f"MongoDB Shopify token lookup failed for shop {shop}: {exc}") from exc
    return token_record.get("accessToken") if token_record else None


def get_shopify_graphql_url() -> str:
    return f"https://{normalize_shop(settings.shopify_shop_domain)}/admin/api/{settings.shopify_api_version}/graphql.json"


def get_shopify_rest_url(path: str) -> str:
    normalized_path = str(path or "").lstrip("/")
    return f"https://{normalize_shop(settings.shopify_shop_domain)}/admin/api/{settings.shopify_api_version}/{normalized_path}"


def normalize_shop(shop: str) -> str:
    return (shop or "").strip().lower().replace("https://", "").replace("http://", "").rstrip("/")


def build_order_search_query(order_id: str) -> str:
    without_hash = order_id.lstrip("#")
    return f"name:{without_hash} OR name:#{without_hash}"


def order_name_matches(candidate: dict[str, Any], normalized_order_id: str) -> bool:
    name = str(candidate.get("name") or "").upper()
    return name == normalized_order_id or name == f"#{normalized_order_id.lstrip('#')}"


def contact_matches(candidate: dict[str, Any], email: str, phone: str) -> bool:
    customer = candidate.get("customer") or {}
    shipping = candidate.get("shippingAddress") or {}
    candidate_emails = [normalize_email(customer.get("email")), normalize_email(candidate.get("email"))]
    candidate_phones = [normalize_phone(customer.get("phone")), normalize_phone(candidate.get("phone")), normalize_phone(shipping.get("phone"))]
    return (email and email in candidate_emails) or (phone and phone in candidate_phones)


def normalize_order_id(order_id: str | None) -> str:
    return str(order_id or "").strip().upper()


def get_numeric_order_id(order_gid: str | None) -> str | None:
    parts = str(order_gid or "").split("/")
    return parts[-1] if parts and parts[-1].isdigit() else None


def normalize_email(email: str | None) -> str:
    return str(email or "").strip().lower()


def normalize_phone(phone: str | None) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) > 10 else digits


def normalize_refund_details(rest_order: dict[str, Any], lookup_order: dict[str, Any]) -> dict[str, Any]:
    currency_code = rest_order.get("currency") or (lookup_order.get("total") or {}).get("currencyCode")
    total_paid = to_number(rest_order.get("total_price") or (lookup_order.get("total") or {}).get("amount"))
    refunds = [normalize_refund(refund, currency_code) for refund in rest_order.get("refunds") or []]
    total_refunded = sum(to_number((refund.get("amount") or {}).get("amount")) for refund in refunds)
    net_payment = max(total_paid - total_refunded, 0)
    payment_status = lookup_order.get("financialStatus") or normalize_status(rest_order.get("financial_status"))
    has_refund = total_refunded > 0 or "refund" in str(payment_status or "").lower()

    return {
        "paymentStatus": payment_status,
        "refundStatus": payment_status if has_refund else "NOT_REFUNDED",
        "refunded": has_refund,
        "totalPaid": money(total_paid, currency_code),
        "totalRefunded": money(total_refunded, currency_code),
        "netPayment": money(net_payment, currency_code),
        "refundCount": len(refunds),
        "refundReasons": [refund.get("note") for refund in refunds if refund.get("note")],
        "refunds": refunds,
        "reply": build_refund_reply(lookup_order.get("name") or rest_order.get("name"), payment_status, total_paid, total_refunded, net_payment, currency_code, refunds),
    }


def normalize_refund(refund: dict[str, Any], currency_code: str | None) -> dict[str, Any]:
    transactions = refund.get("transactions") or []
    refund_transactions = [
        transaction for transaction in transactions
        if str(transaction.get("kind") or "").lower() == "refund"
        and str(transaction.get("status") or "").lower() in {"", "success"}
    ]
    line_items = refund.get("refund_line_items") or []
    order_adjustments = refund.get("order_adjustments") or []
    transaction_amount = sum(to_number(transaction.get("amount")) for transaction in refund_transactions)
    line_item_amount = sum(to_number(item.get("subtotal")) + to_number(item.get("total_tax")) for item in line_items)
    adjustment_amount = sum(abs(to_number(item.get("amount"))) + abs(to_number(item.get("tax_amount"))) for item in order_adjustments)
    amount = transaction_amount if refund_transactions else line_item_amount + adjustment_amount
    return {
        "id": refund.get("id"),
        "createdAt": refund.get("created_at"),
        "note": refund.get("note"),
        "amount": money(amount, currency_code),
        "transactions": [
            {
                "id": transaction.get("id"),
                "kind": transaction.get("kind"),
                "status": transaction.get("status"),
                "gateway": transaction.get("gateway"),
                "amount": money(to_number(transaction.get("amount")), transaction.get("currency") or currency_code),
                "createdAt": transaction.get("created_at"),
            }
            for transaction in transactions
        ],
        "lineItems": [
            {
                "quantity": item.get("quantity") or 0,
                "subtotal": money(to_number(item.get("subtotal")), item.get("currency") or currency_code),
                "tax": money(to_number(item.get("total_tax")), item.get("currency") or currency_code),
                "lineItemId": item.get("line_item_id"),
            }
            for item in line_items
        ],
        "orderAdjustments": [
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "reason": item.get("reason"),
                "amount": money(abs(to_number(item.get("amount"))), item.get("currency") or currency_code),
                "tax": money(abs(to_number(item.get("tax_amount"))), item.get("currency") or currency_code),
            }
            for item in order_adjustments
        ],
    }


def build_refund_reply(order_name, payment_status, total_paid, total_refunded, net_payment, currency_code, refunds):
    notes = [refund.get("note") for refund in refunds if refund.get("note")]
    lines = [
        f"Order No: {order_name or '-'}",
        f"Payment Status: {payment_status or '-'}",
        f"Paid Amount: {format_money(total_paid, currency_code)}",
        f"Refunded Amount: {format_money(total_refunded, currency_code)}",
        f"Net Payment: {format_money(net_payment, currency_code)}",
    ]
    if notes:
        lines.append(f"Refund Reason: {'; '.join(notes)}")
    return "\n".join(lines)


def money(amount, currency_code):
    return {"amount": f"{amount:.2f}", "currencyCode": currency_code}


def format_money(amount, currency_code):
    return f"{amount:.2f}{' ' + currency_code if currency_code else ''}"


def to_number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_status(status):
    return str(status or "").strip().upper() or None
