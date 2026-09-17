"""Compatibility entry point. Production runs python -m station from repository root."""
from station.app import create_app
app = create_app()
