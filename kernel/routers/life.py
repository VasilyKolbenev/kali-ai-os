"""Life endpoints (dashboard, canvas, notifications, briefing, budget, focus,
routines) — extracted from kernel/main.py (T7).

Bodies are byte-identical to the pre-split closures (only ``@app.`` →
``@router.``). Def order preserves main.py registration order (sacred).
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard(request: Request) -> dict[str, Any]:
    """Live dashboard for the mobile app — computed from real agents, not
    stored placeholders. Each widget degrades to a neutral «—» (never a
    fake number) when its agent has no data, so the UI never shows a
    fabricated value as if it were real.
    """
    s = request.app.state
    rt = s.agent_runtime

    async def _safe(agent: str, action: str, args: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return await rt.dispatch(agent, action, args)
        except Exception:
            return None

    # Weather — real, via the (Cyrillic-capable) weather agent.
    city = os.environ.get("KALI_DEFAULT_CITY", "Москва")
    wx = await _safe("weather", "get_weather", {"city": city})
    if wx and wx.get("temperature_c") is not None:
        weather = {"temp": f"{round(wx['temperature_c']):+d}°C",
                   "condition": wx.get("condition", "")}
    else:
        weather = {"temp": "—", "condition": ""}

    # Tasks — real, via the tasks agent summary.
    ts = await _safe("tasks", "get_summary", {})
    if ts:
        tasks = {"active": ts.get("pending", 0),
                 "completed": ts.get("done", 0),
                 "subtitle": f"{ts.get('done', 0)} выполнено сегодня"}
    else:
        tasks = {"active": 0, "completed": 0, "subtitle": "нет задач"}

    # Spending today — real, via life-dashboard. Shown in the «budget»
    # slot the mobile reads, but labeled honestly as spending.
    life = await _safe("life-dashboard", "get_daily_summary", {})
    if life and life.get("total_spending"):
        spending = {"amount": f"₽{life['total_spending']:,}".replace(",", " "),
                    "status": "потрачено сегодня"}
    else:
        spending = {"amount": "—", "status": "нет трат сегодня"}

    return {"weather": weather, "budget": spending, "tasks": tasks}


@router.get("/canvas/widgets")
async def get_canvas_widgets(request: Request) -> dict[str, Any]:
    """Return current live-canvas widgets for initial UI render."""
    runtime = request.app.state.agent_runtime
    try:
        status = await runtime.get_status("live-canvas")
        if not status or status.get("status") != "running":
            return {"widgets": [], "count": 0}
        result = await runtime.dispatch("live-canvas", "list_widgets", {})
        return result
    except Exception:
        return {"widgets": [], "count": 0}


@router.post("/notifications/send")
async def send_notification(request: Request) -> dict[str, str]:
    from kernel.notifications import Notification

    body = await request.json()
    notif = Notification(
        title=body.get("title", "KALI"),
        message=body.get("message", ""),
        priority=body.get("priority", "normal"),
    )
    await request.app.state.notifications.send(notif)
    return {"status": "sent"}


@router.get("/notifications/pending")
async def pending_notifications(request: Request) -> list[dict]:  # type: ignore[type-arg]
    return [
        {
            "title": n.title,
            "message": n.message,
            "priority": n.priority,
            "timestamp": n.timestamp,
        }
        for n in request.app.state.notifications.get_pending()
    ]


@router.get("/briefing/morning")
async def morning_briefing(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = {}  # TODO(#42): collect from agents when running
    text = await request.app.state.briefing.generate_morning_briefing(data)
    return {"text": text}


@router.post("/budget/goal")
async def set_budget_goal(request: Request) -> dict[str, Any]:
    body = await request.json()
    return request.app.state.budget.set_goal(body["category"], body["limit"])


@router.get("/budget/goals")
async def get_budget_goals(request: Request) -> dict[str, Any]:
    return request.app.state.budget.get_goals()


@router.post("/budget/expense")
async def log_budget_expense(request: Request) -> dict[str, Any]:
    body = await request.json()
    return await request.app.state.budget.log_expense(body["amount"], body["category"])


@router.post("/focus/start")
async def start_focus(request: Request) -> dict[str, Any]:
    body = await request.json()
    return await request.app.state.focus.start(
        body.get("duration_minutes", 25), body.get("label", "")
    )


@router.post("/focus/stop")
async def stop_focus(request: Request) -> dict[str, Any]:
    return await request.app.state.focus.stop()


@router.get("/focus/status")
async def focus_status(request: Request) -> dict[str, Any]:
    return request.app.state.focus.get_status()


@router.get("/routines")
async def list_routines(request: Request) -> dict[str, Any]:
    return request.app.state.routines.list_routines()


@router.post("/routines/{name}/execute")
async def execute_routine(name: str, request: Request) -> dict[str, Any]:
    return await request.app.state.routines.execute(name)
