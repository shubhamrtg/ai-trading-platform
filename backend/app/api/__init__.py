"""API router aggregation.

Registers all API route modules with the FastAPI application.
"""

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.system import router as system_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(system_router)

__all__ = ["api_router"]
