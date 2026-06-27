from fastapi import FastAPI

from app.routes import care_panel, customer_info, order_selection, shipping, shopify

app = FastAPI(title="DeoDap Gallabox API", version="1.0.0")


@app.get("/")
async def root():
    return {
        "service": "deodap-gallabox-fastapi",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "deodap-gallabox-fastapi"}


app.include_router(shopify.router, prefix="/api/external/shopify", tags=["shopify"])
app.include_router(shipping.router, prefix="/api/external/shipping", tags=["shipping"])
app.include_router(customer_info.router, prefix="/api/external/customer-info", tags=["customer-info"])
app.include_router(order_selection.router, prefix="/api/external/order-selection", tags=["order-selection"])
app.include_router(care_panel.router, prefix="/api/external/care-panel", tags=["care-panel"])
