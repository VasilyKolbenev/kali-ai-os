"""Tests for persisted, revocable agent consent (M2.2)."""

from pathlib import Path

from kernel.database import Database


async def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "consent.db")
    await db.initialize()
    return db


async def test_set_and_get_consent(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    await db.set_consent("calendar", "approved")
    assert await db.get_consent("calendar") == "approved"
    await db.close()


async def test_set_consent_upserts(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    await db.set_consent("calendar", "approved")
    await db.set_consent("calendar", "revoked")  # same agent -> overwrite
    assert await db.get_consent("calendar") == "revoked"
    await db.close()


async def test_get_consent_missing_returns_none(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    assert await db.get_consent("nope") is None
    await db.close()


async def test_get_all_consents(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    await db.set_consent("calendar", "approved")
    await db.set_consent("email", "revoked")
    assert await db.get_all_consents() == {"calendar": "approved", "email": "revoked"}
    await db.close()


async def test_consent_survives_reopen(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    await db.set_consent("calendar", "approved")
    await db.close()
    db2 = Database(tmp_path / "consent.db")
    await db2.initialize()
    assert await db2.get_consent("calendar") == "approved"  # persisted to disk
    await db2.close()
