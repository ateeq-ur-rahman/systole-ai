from __future__ import annotations

from app.container import Container, build_container
from app.database.db import get_connection


def get_container() -> Container:
    """FastAPI dependency: builds a Container bound to the current
    thread-local SQLite connection. Cheap -- repositories/agents are just
    thin wrappers, so no caching needed."""
    conn = get_connection()
    return build_container(conn)
