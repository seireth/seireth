from fastapi import APIRouter, Depends

from . import assessments, plugins, projects, runtime, scopes, targets
from .dependencies import browser_origin

router = APIRouter(dependencies=[Depends(browser_origin)])
for routes in (projects, targets, scopes, assessments, plugins, runtime):
    router.include_router(routes.router)
