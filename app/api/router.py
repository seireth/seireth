from fastapi import APIRouter, Depends

from . import assessments, plugins, projects, runtime, targets
from .dependencies import browser_origin

router = APIRouter(prefix="/api/v1", dependencies=[Depends(browser_origin)])
for routes in (projects, targets, assessments, plugins, runtime):
    router.include_router(routes.router)
