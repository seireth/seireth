from fastapi import APIRouter

from ..core.config import settings
from .schemas import RuntimeOut

router = APIRouter()


@router.get("/runtime", response_model=RuntimeOut)
def runtime():
    return {
        "sandbox_backend": settings.sandbox_backend,
    }
