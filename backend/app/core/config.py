from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://legaluser:legalpass@localhost:5432/legaldb"
    )
    test_database_url: str = ""

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:3000"]

    # ── AWS / S3 ──────────────────────────────────────────────────────────────
    aws_endpoint_url: str = ""
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_default_region: str = "us-east-1"
    s3_bucket_name: str = "legal-documents"

    # ── SQS ───────────────────────────────────────────────────────────────────
    # Main ingestion queue URL.  Set via SQS_QUEUE_URL env var.
    sqs_queue_url: str = ""
    # Dead-letter queue URL.  Set via SQS_DLQ_URL env var.
    sqs_dlq_url: str = ""

    # ── Upload policy ─────────────────────────────────────────────────────────
    # Maximum file size accepted before issuing a presigned URL (bytes).
    # Default: 50 MB.
    upload_max_size_bytes: int = 52_428_800
    # MIME types the backend will accept.  Validated before the presigned URL
    # is issued so the S3 ContentType condition matches exactly.
    upload_allowed_content_types: list[str] = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    # How long (seconds) the presigned PUT URL remains valid.
    presigned_url_expires_seconds: int = 300

    # ── Clerk ─────────────────────────────────────────────────────────────────
    clerk_secret_key: str = ""
    clerk_jwks_url: str = ""
    # Optional: set to your Clerk issuer URL (e.g. https://<clerk-domain>) to
    # enforce the `iss` claim. Leave empty to skip issuer verification.
    clerk_issuer: str = ""

    # ── Ingestion — Parsing ───────────────────────────────────────────────────
    # Optional LlamaParse API key. When set the worker uses LlamaParse instead
    # of the local PyMuPDF parser.
    llama_parse_api_key: str = ""

    # ── Ingestion — Embeddings ────────────────────────────────────────────────
    # Voyage AI API key. When set the worker calls the Voyage AI endpoint.
    # Leave empty to use the deterministic local fallback (dev/CI only).
    voyage_api_key: str = ""
    # Model identifier stored with every Chunk row. Changing this value
    # requires re-embedding all existing chunks.
    embedding_model: str = "voyage-law-2"
    embedding_model_version: str = "1"
    # Must match the vector dimension in the Chunk.embedding column (1024).
    embedding_dimensions: int = 1024

    # ── Ingestion — Chunking ──────────────────────────────────────────────────
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 64


settings = Settings()
