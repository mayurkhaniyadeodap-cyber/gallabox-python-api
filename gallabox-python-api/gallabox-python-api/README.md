# DeoDap Gallabox FastAPI Backend

Parallel Python implementation of the Gallabox APIs. It can run beside the existing Node server and uses the same environment variable names.

## Setup

```bash
cd gallabox-python-api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

If Shopify uses OAuth, keep `SHOPIFY_AUTH_MODE=oauth` and point `MONGODB_URI` / `MONGODB_DB` to the same Mongo database used by the Node app. The Python API reads the installed token from the `shopify_tokens` collection.

Docs:

```http
http://localhost:8000/docs
```

## Endpoints

```http
POST /api/external/order-selection/latest
POST /api/external/order-selection/verify
POST /api/external/shopify/order-lookup
POST /api/external/shipping/tracking
POST /api/external/shipping/shipment-flow
POST /api/external/customer-info/change-flow
POST /api/external/care-panel/open-tickets
```

All endpoints require:

```http
x-api-key: <EXTERNAL_API_KEY>
Content-Type: application/json
```
