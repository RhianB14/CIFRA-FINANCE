from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.settings import ensure_secure_configuration, get_settings
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_secure_configuration(get_settings())
    yield


app = FastAPI(title="Cifra API", version="0.2.0", lifespan=lifespan)
app.include_router(health_router)
