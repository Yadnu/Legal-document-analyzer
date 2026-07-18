from fastapi import Request
from fastapi.responses import JSONResponse


class AuthError(Exception):
    """Raised when JWT verification fails or the Authorization header is missing."""

    def __init__(self, detail: str = "Authentication required") -> None:
        self.detail = detail
        super().__init__(detail)


class TenantMissingError(Exception):
    """Raised when the verified JWT contains no org_id claim."""

    def __init__(self, detail: str = "No active organization in token") -> None:
        self.detail = detail
        super().__init__(detail)


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "Unauthorized", "detail": exc.detail},
    )


async def tenant_missing_error_handler(
    request: Request, exc: TenantMissingError
) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"error": "Forbidden", "detail": exc.detail},
    )
