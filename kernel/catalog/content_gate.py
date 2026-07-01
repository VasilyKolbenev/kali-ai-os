"""Prose content gate — heuristic scan of a skill's natural-language body.

WS-3 Task 3.7 (§5C of the marketplace design spec). This is the load-bearing
half of the community auto-approve decision and exists because of a specific
hole in the AST safety gate:

    The AST gate (``kernel/builder/safety_gate.py``) scans ``scripts/*.py`` ONLY.
    But most voice-built KALI skills are **script-less Markdown** — the
    ``SKILL.md`` body is injected verbatim into the LLM prompt. A malicious
    skill therefore needs no Python at all: the attack lives in the *prose*
    (prompt-injection / social-engineering). Such a skill passes the AST gate
    trivially (it has no scripts), so AST-pass-alone must NEVER auto-approve.

``scan_prose`` is a conservative first-pass heuristic over that prose. It is
**NOT** a complete prompt-injection detector — adversarial phrasing, obfuscation,
translation, encoding, and novel attacks will slip past simple patterns. The
real backstop is the human review (Vasily at MVP): anything this flags routes to
``pending`` for manual moderation rather than auto-approving. The design bias is
toward false positives (flag → manual review) over false negatives (silently
auto-approving a malicious skill).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Heuristic patterns (case-insensitive). Each entry is (compiled_regex, label).
#
# These target the COMMON, naive shapes of prompt-injection / social-engineering
# in skill prose. They are deliberately broad: a match means "a human should look
# at this", not "this is definitely malicious". See the module docstring for the
# honest statement of limits.
# ---------------------------------------------------------------------------
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Instruction-override / jailbreak openers.
    (
        re.compile(r"\bignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\b", re.I),
        "instruction-override: 'ignore previous/above instructions'",
    ),
    (
        re.compile(r"\bdisregard\s+(?:all\s+|any\s+|your\s+|the\s+|previous\s+|prior\s+|above\b)", re.I),
        "instruction-override: 'disregard your/previous instructions'",
    ),
    (
        re.compile(r"\boverride\s+(?:your|the|all|any|previous|prior)\b", re.I),
        "instruction-override: 'override your/previous instructions'",
    ),
    (
        re.compile(r"\bforget\s+(?:everything|all|your|the\s+above|previous|prior|what\s+you)\b", re.I),
        "instruction-override: 'forget everything/your instructions'",
    ),
    # Persona / role hijack.
    (
        re.compile(r"\byou\s+are\s+now\b", re.I),
        "role-hijack: 'you are now ...'",
    ),
    (
        re.compile(r"\b(?:act|behave|pretend|roleplay|role-play)\s+as\s+(?:if\s+)?(?:a\s+|an\s+|the\s+)?\b", re.I),
        "role-hijack: 'act/pretend as ...'",
    ),
    (
        re.compile(r"\b(?:enter|enable|activate)\s+(?:developer|dev|god|admin|jailbreak|dan)\s+mode\b", re.I),
        "role-hijack: 'enter developer/jailbreak mode'",
    ),
    # System-prompt / secret exfiltration.
    (
        re.compile(r"\bsystem\s+prompt\b", re.I),
        "prompt-exfil: references the 'system prompt'",
    ),
    (
        re.compile(r"\b(?:reveal|disclose|print|repeat|show|output|leak|dump)\s+(?:your|the|all)\b[^.\n]{0,60}\b(?:prompt|instructions|system|rules|guidelines|configuration)\b", re.I),
        "prompt-exfil: 'reveal your prompt/instructions'",
    ),
    (
        re.compile(r"\bexfiltrat", re.I),
        "exfiltration: explicit 'exfiltrate'",
    ),
    (
        re.compile(r"\b(?:reveal|disclose|leak|steal|harvest)\b[^.\n]{0,40}\b(?:api\s*key|secret|token|password|credential)", re.I),
        "secret-exfil: targets api key/secret/token/password/credential",
    ),
    # Data-redirect to an external destination (send the user's data away).
    (
        re.compile(r"\b(?:send|email|post|upload|forward|transmit|exfiltrate|leak)\b[^.\n]{0,80}\b(?:to\s+)?[\w.+-]+@[\w-]+\.[\w.-]+", re.I),
        "data-redirect: send data to an external email address",
    ),
    (
        re.compile(r"\b(?:send|post|upload|forward|transmit|exfiltrate|leak|curl|fetch|wget)\b[^.\n]{0,80}https?://", re.I),
        "data-redirect: send/post data to an external URL",
    ),
    (
        re.compile(r"\b(?:send|forward|share|leak|transmit)\b[^.\n]{0,60}\b(?:user'?s?|the\s+user'?s?|their|his|her)\s+(?:data|info|information|messages?|history|conversation|files?|contacts?|secrets?)", re.I),
        "data-redirect: send the user's data/messages elsewhere",
    ),
    # Consent / permission / safety bypass.
    (
        re.compile(r"\b(?:bypass|skip|ignore|disable|circumvent|evade|turn\s+off)\b[^.\n]{0,40}\b(?:consent|permission|permissions|approval|confirmation|safety|guardrail|security|sandbox|restriction|filter)", re.I),
        "safety-bypass: bypass consent/permission/safety controls",
    ),
    (
        re.compile(r"\bwithout\s+(?:the\s+)?(?:user'?s?\s+)?(?:asking|consent|permission|approval|confirmation|telling)", re.I),
        "safety-bypass: act without asking / without consent",
    ),
    (
        re.compile(r"\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|notify|ask|warn|alert)\s+(?:the\s+)?user\b", re.I),
        "social-engineering: hide the action from the user",
    ),
    # -----------------------------------------------------------------------
    # Russian (RU) needles — most voice-built KALI skills are Russian prose, so
    # an English-only gate is trivially bypassed by writing the injection in RU.
    # Deliberately broad (false-positive bias); \w with re.UNICODE matches
    # Cyrillic, and trailing чему matches inflected endings (е/ь/те/ий/…).
    # -----------------------------------------------------------------------
    # Instruction-override: «игнорируй/забудь/не выполняй … предыдущие/все инструкции».
    (
        re.compile(r"игнорир\w*\s+(?:все\s+|любые\s+)?(?:предыдущ\w*|прежн\w*|вышеуказанн\w*|ранее)", re.I),
        "instruction-override (ru): 'игнорируй предыдущие инструкции'",
    ),
    (
        re.compile(r"забудь\s+(?:всё|все|про\s+все|предыдущ\w*|прежн\w*|свои)\b", re.I),
        "instruction-override (ru): 'забудь всё/предыдущие инструкции'",
    ),
    (
        re.compile(r"не\s+выполняй\s+(?:предыдущ\w*|прежн\w*|прошл\w*|ранее|указанн\w*)", re.I),
        "instruction-override (ru): 'не выполняй предыдущие инструкции'",
    ),
    # Role hijack: «теперь ты …», «притворись/представь, что ты …».
    (
        re.compile(r"\bтеперь\s+ты\b", re.I),
        "role-hijack (ru): 'теперь ты ...'",
    ),
    (
        re.compile(r"(?:притвор\w*|представь|веди\s+себя|действуй)\s+(?:как\s+)?(?:будто\s+|что\s+)?(?:ты\b)?", re.I),
        "role-hijack (ru): 'притворись/веди себя как ...'",
    ),
    # Exfiltration: «отправь/перешли … данные/секрет/ключ/пароль».
    (
        re.compile(r"(?:отправь\w*|перешл\w*|передай\w*|выгруз\w*|слей\b)\s+[^.\n]{0,60}(?:данн\w*|секрет\w*|ключ\w*|парол\w*|токен\w*|информаци\w*|сообщени\w*|перепис\w*)", re.I),
        "exfiltration (ru): 'отправь/перешли данные/секрет/ключ'",
    ),
    # Bypass / hide: «без согласия», «не сообщай пользователю».
    (
        re.compile(r"без\s+(?:согласия|разрешения|подтверждения|ведома|спроса)", re.I),
        "safety-bypass (ru): act без согласия/разрешения",
    ),
    (
        re.compile(r"не\s+(?:сообщ\w*|говор\w*|рассказыв\w*|уведомл\w*|предупрежд\w*)\s+(?:пользовател\w*|юзер\w*)", re.I),
        "social-engineering (ru): hide the action от пользователя",
    ),
)


def scan_prose(text: str | None) -> tuple[bool, list[str]]:
    """Heuristically scan skill prose for prompt-injection / social-engineering.

    Conservative first-pass over a skill's natural-language surface (its
    ``SKILL.md`` body + description). A match flags the content for MANUAL review
    (it does not auto-reject); a clean scan permits auto-approve **in combination
    with** the AST scan of any scripts.

    This is a heuristic, NOT a complete prompt-injection detector. It catches the
    common, naive shapes only — adversarial phrasing, obfuscation, encoding,
    translation, and novel attacks can pass. The human review is the real
    backstop (§5C); the bias is deliberately toward over-flagging.

    Args:
        text: The prose to scan (``SKILL.md`` body + description, concatenated).
            ``None`` / empty is treated as clean (nothing to flag) — emptiness is
            an upstream validation concern, not a moderation signal.

    Returns:
        ``(ok, issues)`` — ``ok`` is True when no pattern matched; ``issues`` is
        the list of human-readable labels for every pattern that matched
        (deduplicated, order-stable). ``ok is False`` iff ``issues`` is non-empty.
    """
    if not text:
        return True, []

    issues: list[str] = []
    seen: set[str] = set()
    for pattern, label in _PATTERNS:
        if pattern.search(text) and label not in seen:
            seen.add(label)
            issues.append(label)

    return (len(issues) == 0), issues
