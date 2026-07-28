from backend_core.bootstrap.app import create_app
from backend_core.bootstrap.lifespan import lifespan

__all__ = [
    "create_app",
    "lifespan",
]
