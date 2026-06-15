"""Tests for the streaming sentence aggregator (P1 — LLM->TTS streaming).

Boundary-detection tests use ``min_chars=0`` (emit every sentence) so they
exercise the splitting logic in isolation; merge-policy tests use the default
``min_chars`` contract that kills mid-speech gaps on short sentences.
"""

from kernel.voice.sentence_buffer import DEFAULT_MIN_CHARS, SentenceBuffer


class TestSentenceBoundaries:
    def test_partial_buffers_without_emitting(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        assert sb.feed("Привет, сэр") == []

    def test_emits_on_sentence_end(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        assert sb.feed("Привет, сэр. ") == ["Привет, сэр."]

    def test_emits_across_deltas(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        assert sb.feed("Какая ") == []
        assert sb.feed("сегодня погода?") == []  # no trailing space yet → buffered
        assert sb.feed(" ") == ["Какая сегодня погода?"]

    def test_multiple_sentences_in_one_feed(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        out = sb.feed("Да. Нет! Может быть? ")
        assert out == ["Да.", "Нет!", "Может быть?"]

    def test_decimal_is_not_a_boundary(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        assert sb.feed("Цена 3.14 рубля. ") == ["Цена 3.14 рубля."]

    def test_ellipsis_is_one_boundary(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        assert sb.feed("Ну... ") == ["Ну..."]

    def test_flush_returns_remaining_partial(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        sb.feed("Последняя мысль без точки")
        assert sb.flush() == "Последняя мысль без точки"
        assert sb.flush() == ""

    def test_flush_after_emit_is_empty(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        sb.feed("Готово. ")
        assert sb.flush() == ""

    def test_newline_ends_a_sentence(self) -> None:
        sb = SentenceBuffer(min_chars=0)
        assert sb.feed("Список:\n") == ["Список:"]


class TestMinCharsMerging:
    def test_first_short_sentence_emits_immediately(self) -> None:
        # Time-to-first-audio: the opener reaches the speaker at once.
        sb = SentenceBuffer()
        assert sb.feed("Хорошо. ") == ["Хорошо."]

    def test_second_short_sentence_is_held(self) -> None:
        # After the fast first emit, merging resumes for the rest.
        sb = SentenceBuffer()
        assert sb.feed("Хорошо. ") == ["Хорошо."]
        assert sb.feed("Да. ") == []

    def test_short_sentences_merge_after_first(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Хорошо. ") == ["Хорошо."]  # first emits
        assert sb.feed("Да. Нет! ") == []  # held (below min_chars)
        out = sb.feed("Сейчас всё подробно расскажу про эту задачу. ")
        assert out == ["Да. Нет! Сейчас всё подробно расскажу про эту задачу."]

    def test_long_sentence_emits_immediately(self) -> None:
        sb = SentenceBuffer()
        text = "Это достаточно длинное предложение для немедленной отправки. "
        assert sb.feed(text) == [text.strip()]

    def test_flush_returns_held_short_sentences(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Готово. ") == ["Готово."]  # first emits
        sb.feed("И ещё. ")  # held
        assert sb.flush() == "И ещё."

    def test_flush_joins_held_sentence_with_partial(self) -> None:
        sb = SentenceBuffer()
        assert sb.feed("Готово. ") == ["Готово."]  # first emits
        sb.feed("И ещё кое-что")  # partial, held
        assert sb.flush() == "И ещё кое-что"

    def test_default_min_chars_is_sane(self) -> None:
        assert 0 < DEFAULT_MIN_CHARS <= 100
