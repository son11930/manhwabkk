import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = os.path.join(BASE_DIR, ".env")
DEFAULT_LOG_PATH = BASE_DIR / "logs" / "backend.jsonl"

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

    # DeepSeek API (Independent configuration from Groq)
    DEEPSEEK_API_KEY: str = Field(default="")
    DEEPSEEK_API_BASE_URL: str = Field(default="https://api.deepseek.com/chat/completions")
    DEEPSEEK_BATCH_PAGES: int = Field(default=5)
    DEEPSEEK_MAX_BATCH_SEGMENTS: int = Field(default=80)
    DEEPSEEK_MAX_BATCH_INPUT_CHARS: int = Field(default=120000)
    DEEPSEEK_TIMEOUT_SECONDS: int = Field(default=90)
    DEEPSEEK_MAX_RETRIES: int = Field(default=2)
    # Semantic recovery is deliberately bounded so an incomplete response never
    # becomes an unbounded paid API loop. Only unresolved segment IDs are sent.
    DEEPSEEK_RECOVERY_RETRY_ROUNDS: int = Field(default=2, ge=0, le=8)
    DEEPSEEK_RECOVERY_MAX_SEGMENTS_PER_CALL: int = Field(default=8, ge=1, le=32)
    DEEPSEEK_RECOVERY_MAX_CALLS: int = Field(default=24, ge=1, le=100)
    DEEPSEEK_RECOVERY_MAX_COST_USD: float = Field(default=0.50, ge=0.0, le=50.0)
    DEEPSEEK_RECOVERY_MAX_OUTPUT_TOKENS: int = Field(default=800, ge=64, le=3000)
    DEEPSEEK_RECOVERY_RETRY_BACKOFF_SECONDS: float = Field(default=1.0, ge=0.0, le=30.0)

    # OCR work is intentionally bounded: detected pages use one base pass and
    # only a small number of crop recoveries.  These values are independent
    # from AI-provider concurrency.
    OCR_BASE_CONCURRENCY: int = Field(default=4, ge=1, le=8)
    OCR_RECOVERY_CONCURRENCY: int = Field(default=1, ge=1, le=4)
    OCR_RECOVERY_MAX_ROIS: int = Field(default=3, ge=0, le=8)
    OCR_RECOVERY_MAX_PIXEL_RATIO: float = Field(default=2.0, ge=0.0, le=4.0)
    OCR_RECOVERY_ENABLED: bool = Field(default=True)

    # Operational logging. The JSON file contains only safe metadata and is rotated.
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE_ENABLED: bool = Field(default=True)
    LOG_FILE_PATH: str = Field(default=str(DEFAULT_LOG_PATH))
    LOG_FILE_MAX_BYTES: int = Field(default=5 * 1024 * 1024)
    LOG_FILE_BACKUP_COUNT: int = Field(default=5)

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
