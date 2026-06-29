import pytest
from kernel.reel.intro import build_intro_line


class _StubResp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tool_calls = None
        self.provider_used = "stub"
        self.latency_ms = 0


class _OkRouter:
    async def route(self, request):  # noqa: ANN001
        assert "повар" in request.text  # description fed into the prompt
        return _StubResp("Привет! Я повар-помощник, подскажу рецепты.")


class _DeadRouter:
    async def route(self, request):  # noqa: ANN001
        raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_build_intro_line_uses_llm_text() -> None:
    line = await build_intro_line("chef", "повар-помощник", _OkRouter())
    assert line == "Привет! Я повар-помощник, подскажу рецепты."


@pytest.mark.asyncio
async def test_build_intro_line_falls_back_to_template_on_error() -> None:
    line = await build_intro_line("chef", "повар-помощник", _DeadRouter())
    assert "chef" in line and "повар-помощник" in line
    assert line  # never empty, never raises


@pytest.mark.asyncio
async def test_build_intro_line_template_on_empty_llm() -> None:
    class _EmptyRouter:
        async def route(self, request):  # noqa: ANN001
            return _StubResp("   ")

    line = await build_intro_line("chef", "повар-помощник", _EmptyRouter())
    assert "chef" in line  # blank LLM output → template
