"""ASGI entrypoint: ``uvicorn fandea.api.app:app``."""

from fandea.api import create_app

app = create_app()
