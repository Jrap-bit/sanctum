from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")
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
    clinic_timezone: str = "Asia/Kolkata"
    encryption_key_path: Path = Path(__file__).resolve().parents[1] / "secrets" / "clinical.key"


@lru_cache
def get_settings():
    return Settings()
