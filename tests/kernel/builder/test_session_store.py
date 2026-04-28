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


def test_session_carries_name_hint() -> None:
    """name_hint is an optional attribute used by /builder/extract to
    pre-populate the LLM's slug suggestion before _build_spec runs.
    """
    from kernel.builder.session_store import BuilderSession

    s = BuilderSession(
        session_id="abc",
        request="трекер воды",
        intent_type="skill",
        template="tracker",
        name_hint="treker-vody",
    )
    assert s.name_hint == "treker-vody"


def test_session_default_name_hint_is_none() -> None:
    from kernel.builder.session_store import BuilderSession

    s = BuilderSession(
        session_id="abc",
        request="трекер воды",
        intent_type="skill",
        template="tracker",
    )
    assert s.name_hint is None
