from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    DATABASE_URL: str = "postgresql://localhost:5432/pdf_forge"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://frontend-one-fawn-73.vercel.app",
        "https://pdf-forge-app.vercel.app",
    ]
    DEBUG: bool = True
    APP_SECRET: str = ""  # Shared password for API access. Set via env var.

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @property
    def database_url_async(self) -> str:
        """Return DATABASE_URL with asyncpg-compatible scheme."""
        url = self.DATABASE_URL
        # Railway uses postgres:// but asyncpg requires postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


settings = Settings()
