"""Approved built-in plugins exposed to the API and assessment worker."""

from .base import PluginRegistry
from .security_headers import PLUGIN as SECURITY_HEADERS_PLUGIN

registry = PluginRegistry(plugins=(SECURITY_HEADERS_PLUGIN,))

__all__ = ["registry"]
