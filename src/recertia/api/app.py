"""ASGI entrypoint: ``uvicorn recertia.api.app:app``."""

from recertia.api import create_app

app = create_app()
