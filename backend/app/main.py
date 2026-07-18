from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health, me
from app.core.config import settings
from app.core.exceptions import (
    AuthError,
    TenantMissingError,
    auth_error_handler,
    tenant_missing_error_handler,
)
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Legal Document Navigator API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AuthError, auth_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(TenantMissingError, tenant_missing_error_handler)  # type: ignore[arg-type]

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(me.router, prefix="/api/v1")

    return app


app = create_app()
