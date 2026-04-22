"""Builder flow — orchestrates intent → wizard → preview → deploy with a single entrypoint per phase."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kernel.builder.deployer import deploy_skill
from kernel.builder.intent_classifier import classify_intent
from kernel.builder.session_store import BuilderSession, SessionStore
from kernel.builder.skill_generator import generate_skill
from kernel.builder.wizard import create_wizard

logger = logging.getLogger(__name__)


class BuilderFlow:
    """High-level orchestrator tying together existing builder modules.

    Connects intent classification, wizard-guided Q&A, spec preview, and skill
    deployment into a single multi-phase flow keyed by a session ID.

    Attributes:
        _store: Session registry used to persist wizard state across calls.
        _agents_dir: Base directory where generated skill subdirectories are written.
        _executor: SkillExecutor used to load the skill after generation.
        _scheduler: Optional Scheduler for cron registration after deploy.
    """

    def __init__(
        self,
        session_store: SessionStore,
        agents_dir: Path,
        skill_executor: Any,
        scheduler: Any | None = None,
    ) -> None:
        """Initialise the BuilderFlow.

        Args:
            session_store: Shared session registry for this flow instance.
            agents_dir: Base directory under which skill directories will be created.
            skill_executor: SkillExecutor instance used during deployment.
            scheduler: Optional Scheduler for cron registration; pass None to skip.
        """
        self._store = session_store
        self._agents_dir = agents_dir
        self._executor = skill_executor
        self._scheduler = scheduler

    def start(self, request: str) -> dict[str, Any]:
        """Phase 1: classify intent, create wizard session, return first question.

        Args:
            request: Natural-language user request describing the desired skill.

        Returns:
            A dict with keys:
                - ``session_id`` (str): Opaque ID for subsequent calls.
                - ``question`` (str | None): First clarifying question to ask the user.
                - ``total_steps`` (int): Total number of questions in the wizard.
                - ``template`` (str | None): Matched template name.

        Raises:
            ValueError: If the intent is ``"agent"`` (out of pilot scope).
        """
        intent = classify_intent(request)
        if intent.type != "skill":
            raise ValueError(
                f"Agent generation out of pilot scope (got intent: {intent.type}). "
                "Pilot supports skill templates only."
            )

        wizard = create_wizard(request, intent)
        sid = self._store.create(
            request=request,
            intent_type=intent.type,
            template=intent.template,
        )
        session = self._store.get(sid)
        session.questions = wizard.questions

        logger.info("BuilderFlow started: sid=%s template=%s steps=%d", sid, intent.template, len(wizard.questions))
        return {
            "session_id": sid,
            "question": session.current_question,
            "total_steps": len(session.questions),
            "template": intent.template,
        }

    def answer(self, session_id: str, text: str) -> dict[str, Any]:
        """Phase 2: record answer, return next question or preview when all answered.

        Args:
            session_id: Session identifier returned by :meth:`start`.
            text: User's answer to the current question.

        Returns:
            When more questions remain — a dict with keys:
                - ``done`` (bool): ``False``.
                - ``question`` (str): Next question.
                - ``step`` (int): Current 0-based step index after recording.
                - ``total_steps`` (int): Total number of questions.

            When all questions are answered — a dict with keys:
                - ``done`` (bool): ``True``.
                - ``preview`` (dict): Assembled skill spec ready for review.

        Raises:
            SessionNotFound: If ``session_id`` is unknown or expired.
        """
        session = self._store.get(session_id)
        session.answers.append(text)
        session.step += 1

        if not session.is_complete:
            return {
                "done": False,
                "question": session.current_question,
                "step": session.step,
                "total_steps": len(session.questions),
            }

        spec = self._build_spec(session)
        session.spec = spec
        return {
            "done": True,
            "preview": spec,
        }

    async def deploy(self, session_id: str) -> dict[str, Any]:
        """Phase 3: materialise skill files, deploy into the runtime, clean up session.

        Args:
            session_id: Session identifier returned by :meth:`start`.

        Returns:
            Result dict from :func:`~kernel.builder.deployer.deploy_skill`, typically
            ``{"status": "deployed", "name": str}`` or ``{"status": "error", "message": str}``.

        Raises:
            SessionNotFound: If ``session_id`` is unknown or expired.
            ValueError: If the wizard has not been completed (spec is None).
        """
        session = self._store.get(session_id)
        if session.spec is None:
            raise ValueError("Cannot deploy: wizard not complete")

        skill_dir = generate_skill(
            name=session.spec["name"],
            template=session.spec["template"],
            description=session.spec["description"],
            config=session.spec["config"],
            agents_dir=self._agents_dir,
        )

        result = await deploy_skill(
            skill_dir=skill_dir,
            skill_executor=self._executor,
            scheduler=self._scheduler,
        )
        self._store.delete(session_id)
        logger.info("BuilderFlow deployed: sid=%s skill=%s status=%s", session_id, skill_dir.name, result.get("status"))
        return result

    def cancel(self, session_id: str) -> None:
        """Phase 4: discard session without deploying.

        Args:
            session_id: Session identifier returned by :meth:`start`.
        """
        self._store.delete(session_id)
        logger.info("BuilderFlow cancelled: sid=%s", session_id)

    def _build_spec(self, session: BuilderSession) -> dict[str, Any]:
        """Materialise a skill spec from session answers (mirrors WizardSession.build_spec)."""
        import re

        name = re.sub(r"[^\w\s-]", "", session.request.lower()).strip()
        name = re.sub(r"[\s_]+", "-", name)[:40].strip("-")
        config: dict[str, Any] = {}
        for i, (q, a) in enumerate(zip(session.questions, session.answers)):
            if "часто" in q or "interval" in q.lower():
                config["interval"] = a
            elif "цел" in q or "goal" in q.lower():
                config["goal"] = a
            elif "уведом" in q or "куда" in q:
                config["notify_channel"] = a
            else:
                config[f"param_{i}"] = a
        return {
            "name": name,
            "description": session.request,
            "type": session.intent_type,
            "template": session.template,
            "config": config,
        }
