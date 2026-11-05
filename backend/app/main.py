"""HTTP API. Start here: `uvicorn app.main:app` (from backend/).

Routes are thin: authentication, then a call into the tool layer / agent / detectors. All access
decisions happen in tools.py and access.py, never here.
"""
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import actions, agent, audit, auth, config, detect, terms, tools
from .access import AccessDenied, Principal
from .data import get_dataset
from .db import get_db
from .docs import get_library

FRONTEND_DIST = config.ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.check_production_secrets()  # refuse to serve with a public signing key
    get_dataset(), get_library(), terms.get_terms()  # load and verify everything once at startup
    yield


app = FastAPI(title="Ascent AI Support Agent", lifespan=lifespan)


def current_user(authorization: str = Header(default="")) -> Principal:
    try:
        return auth.principal_from_token(authorization.removeprefix("Bearer ").strip())
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


def internal_user(principal: Principal = Depends(current_user)) -> Principal:
    if not principal.internal:
        raise HTTPException(403, "Internal users only.")
    return principal


def ops_manager(principal: Principal = Depends(current_user)) -> Principal:
    if principal.role != "ops_manager":
        raise HTTPException(403, "Ops Managers only.")
    return principal


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ConfirmRequest(BaseModel):
    preview_id: str
    token: str


def _me(principal: Principal) -> dict:
    return {"username": principal.user_id, "name": principal.name, "role": principal.role,
            "account_id": principal.account_id, "internal": principal.internal}


@app.get("/api/health")
def health() -> dict:
    dataset = get_dataset()
    return {"status": "ok", "snapshot": dataset.snapshot.isoformat(), "model": config.LLM_MODEL,
            "documents": len(get_library().documents), "terms_documents": len(terms.get_terms())}


@app.get("/api/test-logins")
def test_logins() -> list[dict]:
    """Shown on the login screen so reviewers can pick a role. Passwords are not listed."""
    return [{k: u[k] for k in ("username", "name", "role", "account_id")} for u in auth.users().values()]


@app.post("/api/login")
def login(body: LoginRequest) -> dict:
    try:
        token = auth.login(body.username, body.password)
    except auth.AuthError as exc:
        audit.log(None, "login", body.username[:100], None, None, "denied")
        raise HTTPException(401, str(exc)) from exc
    principal = auth.principal_from_token(token)
    audit.log(principal, "login", principal.user_id, None, None, "allowed")
    return {"token": token, "user": _me(principal)}


@app.get("/api/me")
def me(principal: Principal = Depends(current_user)) -> dict:
    return _me(principal)


@app.post("/api/chat")
def chat(body: ChatRequest, principal: Principal = Depends(current_user)) -> StreamingResponse:
    """Server-sent events: start, plan, tool_call, tool_result, action_preview, error, answer."""
    def stream():
        for event in agent.run_turn(principal, body.conversation_id, body.message.strip()[:4000]):
            yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
    # no-cache / no proxy buffering, so tool calls reach the browser as they happen when hosted
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/actions/confirm")
def confirm_action(body: ConfirmRequest, principal: Principal = Depends(current_user)) -> dict:
    try:
        result = actions.confirm(principal, body.preview_id, body.token, tools.authorize_action)
    except AccessDenied as exc:
        audit.log(principal, "action_confirm", body.preview_id, None, {"error": str(exc)}, "denied")
        raise HTTPException(403, str(exc)) from exc
    except actions.ConfirmationError as exc:
        audit.log(principal, "action_confirm", body.preview_id, None, {"error": str(exc)}, "error")
        raise HTTPException(400, str(exc)) from exc
    audit.log(principal, "action_confirm", body.preview_id, None, result,
              "executed" if result["created"] else "duplicate_ignored")
    return tools.confirmation_view(principal, result)


@app.get("/api/actions")
def list_actions(principal: Principal = Depends(internal_user)) -> list[dict]:
    return tools.visible_actions(principal)


@app.get("/api/dashboard/alerts")
def dashboard_alerts(principal: Principal = Depends(ops_manager)) -> dict:
    alerts = detect.all_alerts(principal)
    audit.log(principal, "dashboard", "all_alerts", None, {"alerts": len(alerts)}, "allowed")
    return {"now": get_dataset().snapshot.isoformat(), "alerts": alerts}


@app.post("/api/dashboard/alerts/{alert_id}/task")
def task_from_alert(alert_id: str, principal: Principal = Depends(ops_manager)) -> dict:
    alert = next((a for a in detect.all_alerts(principal) if a["id"] == alert_id), None)
    if alert is None:
        raise HTTPException(404, "Alert not found (it may have cleared).")
    out = tools.run(principal, "propose_task", {
        "title": f"Follow up: {alert['title']}"[:200], "details": f"{alert['explanation']}\nSuggested: {alert['suggested_action']}",
        "related_id": ", ".join(alert["evidence"]), "alert_id": alert["id"],
    })
    return {"preview": out["_ui"], "message": out["message"]}


@app.get("/api/audit")
def audit_log(conversation_id: str | None = None, user_id: str | None = None, tool: str | None = None,
              decision: str | None = None, limit: int = 50, principal: Principal = Depends(internal_user)) -> dict:
    return tools.run(principal, "audit_lookup", {k: v for k, v in {
        "conversation_id": conversation_id, "user_id": user_id, "tool": tool, "decision": decision,
        "limit": min(limit, 50)}.items() if v})


@app.get("/api/usage")
def usage(_: Principal = Depends(internal_user)) -> dict:
    rows = get_db().query(
        "SELECT conversation_id, model, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens, "
        "SUM(output_tokens) AS output_tokens, SUM(cost_usd) AS cost_usd, AVG(latency_ms) AS avg_latency_ms "
        "FROM llm_usage GROUP BY conversation_id, model")
    total = sum(r["cost_usd"] or 0 for r in rows)
    chats = [r for r in rows if r["conversation_id"] and r["conversation_id"].startswith("conv-")]
    return {"total_cost_usd": round(total, 6), "conversations": len(chats),
            "avg_cost_per_conversation_usd": round(sum(r["cost_usd"] for r in chats) / len(chats), 6) if chats else 0,
            "by_conversation": rows}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        file = (FRONTEND_DIST / path).resolve()
        inside = file.is_relative_to(FRONTEND_DIST.resolve())
        return FileResponse(file if path and inside and file.is_file() else FRONTEND_DIST / "index.html")
