from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    external_api_key: str = ""

    shopify_enabled: bool = False
    shopify_auth_mode: str = "token"
    shopify_shop_domain: str = ""
    shopify_admin_access_token: str = ""
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_scopes: str = "read_orders,read_customers,read_products,read_fulfillments"
    shopify_redirect_uri: str = ""
    shopify_api_version: str = "2025-04"
    shopify_timeout_ms: int = 10000

    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    mongodb_db: str = "email_ticket_demo"

    ship_panel_tracking_url: str = "https://ship.deodap.in/api/webhook/get-order-tracking"
    ship_panel_public_tracking_base_url: str = "https://ship.deodap.in/tracking"
    ship_panel_app_secret: str = ""
    ship_panel_referer: str = ""
    ship_panel_timeout_ms: int = 10000

    care_panel_base_url: str = "https://care.deodap.in"
    care_panel_bearer_token: str = ""
    care_panel_timeout_ms: int = 15000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
