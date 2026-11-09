"""Read and narrow write HTTP adapters for the J.A.R.V.I.S. local API."""

from .app import create_app

__all__ = ["create_app"]
