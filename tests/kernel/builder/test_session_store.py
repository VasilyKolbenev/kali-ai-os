import pytest
from kernel.builder.session_store import SessionStore, SessionNotFound


def test_create_and_get_session() -> None:
    store = SessionStore()
    sid = store.create(request="Напомни пить воду", intent_type="skill", template="reminder")
    session = store.get(sid)
    assert session.request == "Напомни пить воду"
    assert session.intent_type == "skill"
    assert session.template == "reminder"


def test_get_unknown_raises() -> None:
    store = SessionStore()
    with pytest.raises(SessionNotFound):
        store.get("nonexistent")


def test_delete_session() -> None:
    store = SessionStore()
    sid = store.create(request="x", intent_type="skill", template=None)
    store.delete(sid)
    with pytest.raises(SessionNotFound):
        store.get(sid)


def test_ttl_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sessions older than TTL are evicted on access."""
    import time
    now = [1000.0]
    monkeypatch.setattr("kernel.builder.session_store.time.monotonic", lambda: now[0])

    store = SessionStore(ttl_seconds=60)
    sid = store.create(request="x", intent_type="skill", template=None)
    now[0] = 1061.0  # advance past TTL
    with pytest.raises(SessionNotFound):
        store.get(sid)


def test_delete_nonexistent_is_noop() -> None:
    """delete() on unknown session_id must not raise."""
    store = SessionStore()
    store.delete("ghost-session-id")  # must not raise
