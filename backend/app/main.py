from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.core.database import create_database_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_directory.mkdir(parents=True, exist_ok=True)
    (settings.storage_directory / "screenshots").mkdir(exist_ok=True)
    create_database_tables()
    yield


app = FastAPI(title="Loop API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.mount("/storage", StaticFiles(directory=settings.storage_directory), name="storage")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "loop-api"}
