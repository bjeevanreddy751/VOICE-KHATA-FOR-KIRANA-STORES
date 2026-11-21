"""
Root entrypoint for Vercel and ASGI server deployment.
Exports the FastAPI application instance `app`.
"""

from backend.app import app

__all__ = ["app"]
