from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://legaluser:legalpass@localhost:5432/legaldb"
    )
    test_database_url: str = ""

    cors_origins: list[str] = ["http://localhost:3000"]

    aws_endpoint_url: str = ""
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_default_region: str = "us-east-1"
    s3_bucket_name: str = "legal-documents"

    clerk_secret_key: str = ""
    clerk_jwks_url: str = ""
    # Optional: set to your Clerk issuer URL (e.g. https://<clerk-domain>) to
    # enforce the `iss` claim. Leave empty to skip issuer verification.
    clerk_issuer: str = ""


settings = Settings()
