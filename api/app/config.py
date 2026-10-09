"""Runtime configuration (env vars, overridable via .env)."""
from functools import lru_cache

from pydantic import model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project: str = ""
    gcp_location: str = "us"                   # shared endpoint verified for all configured models
    use_vertex: bool = True                     # False -> Gemini Developer API with GEMINI_API_KEY
    gemini_api_key: str = ""

    model_main: str = "gemini-3.8-flash"
    model_lite: str = "gemini-3.1-flash-lite"
    model_live: str = "gemini-3.8-live"
    model_live_fallback: str = "gemini-3.8-live" # no independent backup model verified

    # storage: "firestore" in cloud, "memory" for local development without GCP
    store_backend: str = "memory"
    evidence_bucket: str = ""
    use_dlp: bool = False

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    console_key: str = ""
    share_secret: str = "dev-only-change-me"
    open_workspace: bool = False               # browser-owned cases without a login prompt
    case_collection: str = "cases"

    tasks_queue: str = ""                       # projects/.../locations/.../queues/...
    public_base_url: str = ""
    tasks_service_account: str = ""             # verified OIDC identity for reminder callbacks

    @model_validator(mode="after")
    def production_origins(self):
        origins = [x.strip() for x in self.cors_origins.split(",")]
        if self.store_backend == "firestore" and ("*" in origins or not all(origins)):
            raise ValueError("Production CORS requires explicit allowed origins")
        if self.store_backend == "firestore" and (len(self.share_secret.strip()) < 32 or (not self.open_workspace and len(self.console_key.strip()) < 32)):
            raise ValueError("Cloud storage requires private signing and responder keys of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
