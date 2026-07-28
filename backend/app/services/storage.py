# Built with Spec4 AI - https://spec4.ai
"""Storage abstraction over stored_records: get/set semantics for StoredRecord."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import StoredRecord


async def get_record(session: AsyncSession, key: str) -> StoredRecord | None:
    """Fetch a stored record by its key.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session to query through.
        key: The record's primary key.

    Returns:
        The matching StoredRecord, or None if no record exists for that key.
    """
    result = await session.execute(select(StoredRecord).where(StoredRecord.key == key))
    return result.scalar_one_or_none()


async def set_record(session: AsyncSession, *, key: str, value: str, written_by: str) -> StoredRecord:
    """Write a stored record, creating it or overwriting its existing value.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session to write through.
        key: The record's primary key.
        value: The value to store.
        written_by: The name of the app writing this record.

    Returns:
        The persisted StoredRecord.
    """
    record = await get_record(session, key)
    if record is None:
        record = StoredRecord(key=key, value=value, written_by=written_by)
        session.add(record)
    else:
        record.value = value
        record.written_by = written_by

    await session.commit()
    return record
