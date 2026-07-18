from fastapi import APIRouter, Depends

from app.core.deps import get_current_tenant, get_current_user
from app.schemas.auth import MeResponse, TenantContext, UserContext

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=MeResponse)
async def get_me(
    user: UserContext = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
) -> MeResponse:
    return MeResponse(
        user_id=user.user_id,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.slug,
    )
