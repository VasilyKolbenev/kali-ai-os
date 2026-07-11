"""The persona must instruct gender-aware address + occupation-aware wording."""
from kernel.jarvis_persona import get_prompt


def test_persona_mentions_gender_aware_address() -> None:
    p = get_prompt()
    assert "мэм" in p          # female address option exists
    assert "Пол" in p          # ties address/grammar to the stored fact


def test_persona_mentions_occupation_adaptation() -> None:
    assert "Род занятий" in get_prompt()
