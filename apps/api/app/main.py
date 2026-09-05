from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.settings import cors_origins, ensure_secure_configuration, get_settings
from app.routers.accounts import router as accounts_router
from app.routers.auth import router as auth_router
from app.routers.cards import router as cards_router
from app.routers.dashboard import router as dashboard_router
from app.routers.health import router as health_router
from app.routers.recurring import router as recurring_router
from app.routers.taxonomy import router as taxonomy_router
from app.routers.transactions import router as transactions_router
from app.services.storage import ObjectStorage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ensure_secure_configuration(settings)
    storage = ObjectStorage()
    try:
        await storage.ensure_bucket()
    except Exception:
        if settings.environment == "production":
            raise
    yield


app = FastAPI(title="Cifra API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(cors_origins(get_settings())),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(cards_router)
app.include_router(transactions_router)
app.include_router(taxonomy_router)
app.include_router(recurring_router)
app.include_router(dashboard_router)
