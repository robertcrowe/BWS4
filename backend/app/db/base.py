# Built with Spec4 AI - https://spec4.ai
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models; Alembic autogenerate targets this."""
