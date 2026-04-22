"""Demo flow — prints timestamped trace of a builder session for screen recording.

Usage: uv run python tools/demo_builder.py --request "напомни пить воду каждые 2 часа"
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is on sys.path when run directly (uv run python tools/demo_builder.py)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore


async def demo(request: str, mock_intent: bool = False) -> None:
    """Run a full builder flow with canned answers, printing a timestamped trace.

    Args:
        request: Natural-language request describing the desired skill.
        mock_intent: If True, skip LLM call and use a stub intent classifier.
    """
    if mock_intent:
        import kernel.builder.flow as _flow_module

        class _MockIntent:
            type = "skill"
            template = "reminder"
            confidence = 0.9
            reason = "mocked"

        _flow_module.classify_intent = lambda req: _MockIntent()  # type: ignore[assignment]

    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=Path("agents-demo"),
        skill_executor=executor,
    )

    start = time.monotonic()

    def log(msg: str) -> None:
        elapsed = time.monotonic() - start
        print(f"[{elapsed:5.1f}s] {msg}")

    log(f"USER: {request}")
    r = flow.start(request)
    sid = r["session_id"]
    log(f"JARVIS: {r['question']}")

    canned = ["каждые 2 часа", "с 9 утра", "голосом"]
    total = r["total_steps"]
    for i in range(total):
        a = canned[i] if i < len(canned) else "default"
        log(f"USER: {a}")
        resp = flow.answer(sid, a)
        if resp.get("done"):
            log(f"JARVIS: Я создам {resp['preview']['name']}. Запускать?")
        else:
            log(f"JARVIS: {resp['question']}")

    log("USER: да, запускай")
    result = await flow.deploy(sid)
    log(f"JARVIS: Готово! {result.get('name', '')} запущен.")
    log(f"Total time: {time.monotonic() - start:.1f}s")


def main() -> None:
    """Entry point for the demo CLI."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--request", default="напомни пить воду каждые 2 часа")
    p.add_argument(
        "--mock-intent",
        action="store_true",
        help="Skip LLM call; use stub intent classifier (no API key needed)",
    )
    args = p.parse_args()
    asyncio.run(demo(args.request, mock_intent=args.mock_intent))


if __name__ == "__main__":
    main()
