from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.services.readiness import DependencyCheck, evaluate_readiness, get_dependency_checks

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "alive", "service": "cifra-api"}


@router.get("/ready")
async def ready(
    response: Response,
    checks: Annotated[list[DependencyCheck], Depends(get_dependency_checks)],
) -> dict[str, str | dict[str, str]]:
    dependencies = await evaluate_readiness(checks)
    is_ready = all(value == "healthy" for value in dependencies.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if is_ready else "not_ready", "dependencies": dependencies}
