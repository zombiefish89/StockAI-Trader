from fastapi import APIRouter

from backend.app.api.routes_analyze import router as analyze_router
from backend.app.api.routes_symbols import router as symbols_router
from backend.app.api.routes_history import router as history_router

router = APIRouter()
router.include_router(analyze_router)
router.include_router(symbols_router)
router.include_router(history_router)

__all__ = ["router"]
