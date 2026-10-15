from fastapi import APIRouter, Depends

from ..assessments.profiles import public_catalog
from ..plugins.registry import registry as plugin_registry
from . import assessments, projects, targets
from .dependencies import browser_origin

router = APIRouter(prefix="/api/v1", dependencies=[Depends(browser_origin)])
for routes in (projects, targets, assessments):
    router.include_router(routes.router)


@router.get("/plugins")
def list_plugins():
    """List built-in plugins that callers may select for assessments."""

    return plugin_registry.catalog()


@router.get("/runtime/profiles")
def profiles():
    return public_catalog()
