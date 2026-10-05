from fastapi import APIRouter

from ..plugins.registry import registry as plugin_registry

router = APIRouter()


@router.get("/plugins")
def list_plugins():
    """List built-in plugins that callers may select for assessments."""

    return plugin_registry.catalog()
