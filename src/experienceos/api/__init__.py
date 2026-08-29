"""API package (#018): a thin FastAPI shell over the service layer."""

from experienceos.api.app import create_app

__all__ = ["create_app"]
