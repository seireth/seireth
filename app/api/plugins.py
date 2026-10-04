from fastapi import APIRouter

from ..plugins import registry as plugin_registry

router = APIRouter()


@router.get("/api/v1/plugins")
def list_plugins():
    """List built-in plugins that callers may select for assessments."""

    return plugin_registry.catalog()
