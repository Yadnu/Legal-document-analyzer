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


class ValidationError(Exception):
    """Raised when user-supplied input fails business-rule validation (→ 422).

    Examples: disallowed content type, file too large.
    Distinct from Pydantic's own ValidationError which FastAPI handles separately.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class NotFoundError(Exception):
    """Raised when a requested resource does not exist for this tenant (→ 404)."""

    def __init__(self, detail: str = "Resource not found") -> None:
        self.detail = detail
        super().__init__(detail)


class AwsError(Exception):
    """Raised when an AWS (S3/SQS) call fails (→ 502).

    The ``detail`` is always a sanitised user-facing message; boto3 internals
    are logged server-side and never forwarded to the client.
    """

    def __init__(self, detail: str = "An upstream service error occurred") -> None:
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# FastAPI exception handlers
# ---------------------------------------------------------------------------


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


async def validation_error_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "Unprocessable Entity", "detail": exc.detail},
    )


async def not_found_error_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "Not Found", "detail": exc.detail},
    )


async def aws_error_handler(request: Request, exc: AwsError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "Bad Gateway", "detail": exc.detail},
    )
