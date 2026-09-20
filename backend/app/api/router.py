"""Top-level API router for Loop resources."""

from fastapi import APIRouter

from app.api import applications, journeys, runs

api_router = APIRouter()
api_router.include_router(applications.router, prefix="/applications", tags=["applications"])
api_router.include_router(journeys.router, prefix="/journeys", tags=["journeys"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
