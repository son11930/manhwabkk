import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = os.path.join(BASE_DIR, ".env")

class Settings(BaseSettings):
    APP_NAME: str = Field(default="Manga AI Translation API")
    APP_ENV: str = Field(default="local")
    DEBUG: bool = Field(default=True)
    API_V1_STR: str = Field(default="/api/v1")

    SECRET_KEY: str = Field(default="local-dev-secret-key-do-not-use-in-prod")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=1440)
    SUPER_ADMIN_EMAIL: str = Field(default="admin@manhwabkk.local")
    SUPER_ADMIN_PASSWORD: str = Field(default="supersecurepassword123!")

    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./manga_app.db")

    # Cloudflare R2 Storage
    R2_ACCOUNT_ID: str = Field(default="1234567890abcdef1234567890abcdef")
    R2_ACCESS_KEY_ID: str = Field(default="test_access_key")
    R2_SECRET_ACCESS_KEY: str = Field(default="test_secret_key")
    R2_BUCKET_NAME: str = Field(default="manga-thai-storage")
    R2_DEV_URL: str = Field(default="https://pub-test.r2.dev")

    # Groq API
    GROQ_API_KEY: str = Field(default="test_groq_api_key")
    GROQ_MODEL: str = Field(default="llama-3.3-70b-versatile")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def r2_endpoint_url(self) -> str:
        """Returns the Cloudflare R2 S3-compatible endpoint URL."""
        return f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

settings = Settings()
