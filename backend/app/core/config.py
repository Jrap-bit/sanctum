from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict



class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore")
    database_url: str = "postgresql+psycopg://sanctum:sanctum_local@localhost:5433/sanctum"
    allowed_origin: str = "http://localhost:3000"
    # Explicit local origins for the frontend and Swagger UI. Configure for HTTPS deployment.
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000",
                                 "http://localhost:8000", "http://127.0.0.1:8000"]
    cookie_secure: bool = False  # Local HTTP only; set true when deploying behind HTTPS.
    session_hours: int = Field(default=8, ge=1, le=24)
    activation_token_hours: int = Field(default=24, ge=1, le=72)
    reset_token_minutes: int = Field(default=30, ge=5, le=120)
    tesseract_command: str = "tesseract"
    ocr_language: str = "eng"
    summary_model: str = "qwen3:4b"
    # Runtime is a URL: host Ollama, Docker Model Runner, or the containerised CPU profile.
    llm_engine: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "local"
    llm_models: list[str] = ["qwen3:4b", "qwen3:1.7b", "llama3.2:3b", "gemma4:e2b"]
    llm_allowed_hosts: list[str] = ["127.0.0.1", "localhost", "::1", "host.docker.internal",
                                    "model-runner.docker.internal", "llm"]
    llm_timeout_seconds: int = Field(default=300, ge=10, le=900)
    llm_max_output_tokens: int = Field(default=3000, ge=100, le=8000)

    redis_url: str = "redis://localhost:6379/0"
    session_idle_minutes: int = Field(default=15, ge=1, le=120)
    cache_ttl_seconds: int = Field(default=60, ge=1, le=3600)
    raw_text_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    ws_ticket_seconds: int = Field(default=30, ge=5, le=120)

    text_extractor: str = "pdfium"
    ocr_engine: str = "tesseract"

    store_backend: str = "filesystem"
    store_path: Path = Path(__file__).resolve().parents[2] / "storage" / "objects"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "sanctum-originals"
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # Operator secret wrapping the data key. Base64url of 32 bytes, or read from master_key_path.
    master_key: SecretStr | None = None
    master_key_path: Path = Path(__file__).resolve().parents[2] / "secrets" / "master.key"
    wrapped_keys_path: Path = Path(__file__).resolve().parents[2] / "secrets" / "data-keys.json"

    backup_path: Path = Path(__file__).resolve().parents[2] / "storage" / "backups"
    backup_key_path: Path = Path(__file__).resolve().parents[2] / "secrets" / "backup.key"

    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None

    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    clinic_timezone: str = "Asia/Kolkata"


@lru_cache
def get_settings():
    return Settings()
