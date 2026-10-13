from fastapi import APIRouter

from ..assessments.profiles import public_catalog

router = APIRouter()


@router.get("/runtime/profiles")
def profiles():
    return public_catalog()
