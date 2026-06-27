from motor.motor_asyncio import AsyncIOMotorClient
import certifi

from app.config import settings

mongo_options = {}

uri_lower = settings.mongodb_uri.lower()

if settings.mongodb_uri.startswith("mongodb+srv://") or "tls=true" in uri_lower or "ssl=true" in uri_lower:
    mongo_options["tlsCAFile"] = certifi.where()

client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=10000, **mongo_options)
db = client[settings.mongodb_db]
