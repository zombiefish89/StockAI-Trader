from fastapi import APIRouter

from backend.app.api.routes_analyze import router as analyze_router

router = APIRouter()
router.include_router(analyze_router)

__all__ = ["router"]
