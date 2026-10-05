from fastapi import APIRouter

from ..core.config import settings
from .schemas import RuntimeOut

router = APIRouter()


@router.get("/runtime", response_model=RuntimeOut)
def runtime():
    return {
        "sandbox_backend": settings.sandbox_backend,
        "default_target_image": settings.docker_target_image,
        "allowed_target_images": settings.docker_allowed_target_images,
    }
