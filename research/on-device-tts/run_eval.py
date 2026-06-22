"""Eval runner for on-device TTS candidates.

Pipeline per eval-set item: synthesize → transcribe (STT round-trip) → score
intelligibility (WER/CER) + speed (RTF). Synthesis and STT are injected as
callables so this runner is engine-agnostic (F5 today, a distilled/quantized
student tomorrow) and unit-testable without a model.

Wire ``main()`` to KALI's real engines (kernel.voice) when running for real —
that path needs the model + GPU/Accelerate, so it is documented, not hardcoded.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from metrics import char_error_rate, real_time_factor, word_error_rate

HERE = Path(__file__).parent

# A synth fn takes the text to speak and returns
# (audio_ref, synth_seconds, audio_seconds): audio_ref is whatever the STT fn
# accepts (a wav path or array). An STT fn takes that audio_ref → transcript.
SynthFn = Callable[[str], tuple[Any, float, float]]
SttFn = Callable[[Any], str]


def load_eval_set(path: Path | str = HERE / "eval_set.jsonl") -> list[dict[str, Any]]:
    """Load the JSONL eval set into a list of item dicts."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate(
    items: list[dict[str, Any]], synth: SynthFn, stt: SttFn
) -> list[dict[str, Any]]:
    """Run synth → STT → score for every item.

    The WER/CER reference is the item's ``spoken`` field if present (the spoken
    form of normalization items like «14:30»), else ``text``. Items that fail to
    synthesize are recorded with an ``error`` and skipped from aggregates.

    Args:
        items: Eval-set entries (need at least ``id`` and ``text``).
        synth: Engine synthesis callable.
        stt: Engine transcription callable.

    Returns:
        Per-item result dicts with wer/cer/rtf or an error.
    """
    results: list[dict[str, Any]] = []
    for item in items:
        ref = item.get("spoken", item["text"])
        row: dict[str, Any] = {"id": item["id"], "category": item.get("category", "")}
        try:
            audio, synth_s, audio_s = synth(item["text"])
            hyp = stt(audio)
            row.update(
                hypothesis=hyp,
                wer=word_error_rate(ref, hyp),
                cer=char_error_rate(ref, hyp),
                rtf=real_time_factor(synth_s, audio_s),
            )
        except Exception as exc:  # engine/runtime failure on one item ≠ abort run
            row["error"] = f"{type(exc).__name__}: {exc}"
        results.append(row)
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate WER/CER/RTF means overall and per category."""
    ok = [r for r in results if "error" not in r]

    def _means(rows: list[dict[str, Any]]) -> dict[str, float]:
        if not rows:
            return {}
        return {
            "wer": statistics.fmean(r["wer"] for r in rows),
            "cer": statistics.fmean(r["cer"] for r in rows),
            "rtf": statistics.fmean(r["rtf"] for r in rows),
            "n": len(rows),
        }

    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in ok:
        by_cat[r["category"]].append(r)

    return {
        "overall": _means(ok),
        "by_category": {c: _means(rows) for c, rows in by_cat.items()},
        "errors": [r for r in results if "error" in r],
    }


def write_report(
    results: list[dict[str, Any]], summary: dict[str, Any], out_dir: Path | str
) -> None:
    """Write results.json + a human-readable report.md."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(
        json.dumps({"summary": summary, "items": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ov = summary.get("overall", {})
    lines = [
        "# On-device TTS eval report",
        "",
        f"Items: {len(results)} | overall WER {ov.get('wer', float('nan')):.3f} "
        f"· CER {ov.get('cer', float('nan')):.3f} · RTF {ov.get('rtf', float('nan')):.3f}",
        "",
        "| category | n | WER | CER | RTF |",
        "|---|---|---|---|---|",
    ]
    for cat, m in summary.get("by_category", {}).items():
        lines.append(
            f"| {cat} | {m.get('n', 0)} | {m.get('wer', 0):.3f} | "
            f"{m.get('cer', 0):.3f} | {m.get('rtf', 0):.3f} |"
        )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Run the eval against KALI's real engines.

    TODO(wire): build ``synth`` from KALI's F5 TTS (kernel/voice) and ``stt``
    from the faster-whisper STT — or GigaAM2 (MIT, the Russian ASR accuracy
    leader per the 2026 research) for a tighter intelligibility reference.
    Measure RTF on CPU specifically (the on-device gate), not just GPU. This
    entry point needs the model + accelerator, so it is intentionally a stub.
    """
    raise NotImplementedError(
        "Wire synth (KALI F5 TTS) + stt (faster-whisper or GigaAM2) here, then:\n"
        "  items = load_eval_set(); res = evaluate(items, synth, stt)\n"
        "  write_report(res, summarize(res), HERE / 'runs' / '<label>')"
    )


if __name__ == "__main__":
    main()
