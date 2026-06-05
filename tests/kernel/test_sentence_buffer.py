"""Tests for the streaming sentence aggregator (P1 — LLM->TTS streaming)."""

from kernel.voice.sentence_buffer import SentenceBuffer


class TestSentenceBuffer:
    def test_partial_buffers_without_emitting(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Привет, сэр") == []

    def test_emits_on_sentence_end(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Привет, сэр. ") == ["Привет, сэр."]

    def test_emits_across_deltas(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Какая ") == []
        assert sb.feed("сегодня погода?") == []  # no trailing space yet → buffered
        assert sb.feed(" ") == ["Какая сегодня погода?"]

    def test_multiple_sentences_in_one_feed(self) -> None:
        sb = SentenceBuffer()
        out = sb.feed("Да. Нет! Может быть? ")
        assert out == ["Да.", "Нет!", "Может быть?"]

    def test_decimal_is_not_a_boundary(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Цена 3.14 рубля. ") == ["Цена 3.14 рубля."]

    def test_ellipsis_is_one_boundary(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Ну... ") == ["Ну..."]

    def test_flush_returns_remaining_partial(self) -> None:
        sb = SentenceBuffer()
        sb.feed("Последняя мысль без точки")
        assert sb.flush() == "Последняя мысль без точки"
        assert sb.flush() == ""

    def test_flush_after_emit_is_empty(self) -> None:
        sb = SentenceBuffer()
        sb.feed("Готово. ")
        assert sb.flush() == ""

    def test_newline_ends_a_sentence(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Список:\n") == ["Список:"]
