"""Deterministic chat answers for the mock provider (ADR-0015).

Keyword routing picks real chat tools; the answer is built only from their results, so
offline replies never invent statuses or numbers. Not a substitute for a real model.
"""

import json
import re
from typing import Any

from agent_hq.llm.base import ModelRequest, ModelResponse, ToolCall
from agent_hq.llm.mock import estimate_usage

_WRAPPED = re.compile(r"<untrusted_tool_output[^>]*>\n(.*)\n</untrusted_tool_output>", re.DOTALL)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_SPANISH = re.compile(
    r"\b(qué|que|cómo|como|cuál|cual|hay|tareas?|equipo|aprobaci\w*|pendientes?|crea|haz|"
    r"analiza|revisa|implementa|agrega|estado|hola|proyecto|sabes|dime|necesito|quiero|"
    r"para|el|la|los|las|del|por)\b",
    re.IGNORECASE,
)
_PROPOSE = re.compile(
    r"\b(crea|crear|haz|hacer|analiza|analizar|revisa|revisar|implementa|implementar|agrega|"
    r"agregar|arregla|arreglar|create|make|analy[sz]e|review|implement|add|fix|build)\b",
    re.IGNORECASE,
)
_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("chat.list_approvals", re.compile(r"aprob|approv|pendiente|pending|decid", re.IGNORECASE)),
    ("chat.team", re.compile(r"equipo|team|agente|agent|qui[eé]n|who", re.IGNORECASE)),
    (
        "chat.search_knowledge",
        re.compile(
            r"brain|conocimiento|knowledge|pol[ií]tica|policy|servicio|service|sabes|know",
            re.IGNORECASE,
        ),
    ),
    (
        "chat.list_tasks",
        re.compile(r"tarea|task|estado|status|fall|fail|progres|haciendo|doing", re.IGNORECASE),
    ),
]


def _reply(
    request: ModelRequest, content: str, calls: list[ToolCall] | None = None
) -> ModelResponse:
    return ModelResponse(
        content=content,
        tool_calls=calls or [],
        parsed=None,
        usage=estimate_usage(request, content),
    )


def _project_key(text: str, hints: dict[str, Any]) -> str | None:
    if hints.get("scope_project_key"):
        return str(hints["scope_project_key"])
    projects = hints.get("projects") or []
    lowered = text.lower()
    for p in projects:
        if p["key"].lower() in lowered or p["name"].lower() in lowered:
            return str(p["key"])
    return str(projects[0]["key"]) if len(projects) == 1 else None


def _plan(text: str, hints: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    task_id = _UUID.search(text)
    if task_id:
        return [("chat.get_task", {"task_id": task_id.group(0)})]
    if _PROPOSE.search(text) and not text.rstrip().endswith("?"):
        key = _project_key(text, hints)
        if key is None:
            return [("chat.overview", {})]
        title = re.split(r"[.\n]", text.strip(), maxsplit=1)[0][:80]
        return [
            (
                "chat.propose_task",
                {"project_key": key, "title": title.strip() or "New task", "request": text},
            )
        ]
    calls: list[tuple[str, dict[str, Any]]] = []
    for name, pattern in _INTENTS:
        if pattern.search(text):
            args: dict[str, Any] = {"query": text[:300]} if name == "chat.search_knowledge" else {}
            calls.append((name, args))
    return calls[:3] or [("chat.overview", {})]


def _bullets(lines: list[str], empty: str) -> str:
    return "\n".join(f"• {line}" for line in lines) if lines else empty


def _compose(name: str, args: dict[str, Any], result: dict[str, Any], es: bool) -> str:
    def t(spanish: str, english: str) -> str:
        return spanish if es else english

    if "denied" in result or "error" in result:
        reason = result.get("denied") or result.get("error")
        return t(f"No pude consultar eso: {reason}.", f"I could not check that: {reason}.")
    if name == "chat.overview":
        projects = ", ".join(p["key"] for p in result["projects"]) or "—"
        statuses = ", ".join(f"{n} {s}" for s, n in sorted(result["tasks_by_status"].items()))
        text = t(
            f"Panorama: {len(result['projects'])} proyecto(s) ({projects}). "
            f"Tareas: {statuses or 'ninguna'}. Aprobaciones pendientes: "
            f"{result['approvals_pending']}.",
            f"Overview: {len(result['projects'])} project(s) ({projects}). "
            f"Tasks: {statuses or 'none'}. Pending approvals: {result['approvals_pending']}.",
        )
        failures = [f"{f['title']} ({f['link']})" for f in result["recent_failures"]]
        if failures:
            text += (
                "\n" + t("Fallas recientes:", "Recent failures:") + "\n" + _bullets(failures, "")
            )
        return text
    if name == "chat.list_tasks":
        lines = [f"{x['title']} — {x['status']} ({x['link']})" for x in result["tasks"]]
        return (
            t("Tareas recientes:", "Recent tasks:")
            + "\n"
            + _bullets(lines, t("No hay tareas todavía.", "There are no tasks yet."))
        )
    if name == "chat.get_task":
        summary = (result.get("summary") or {}).get("outcome")
        text = f"{result['title']} — {result['status']} ({result['link']})"
        if summary:
            text += f"\n{summary}"
        if result.get("pending_approvals"):
            text += "\n" + t(
                "Espera tu aprobación en la página de Aprobaciones.",
                "It is waiting for your approval on the Approvals page.",
            )
        return text
    if name == "chat.list_approvals":
        lines = [
            f"{a['task']}: {a['action']} → {a['target']} ({a['risk']})" for a in result["pending"]
        ]
        if not lines:
            return t("No hay aprobaciones pendientes.", "There are no pending approvals.")
        return (
            t("Aprobaciones pendientes:", "Pending approvals:")
            + "\n"
            + _bullets(lines, "")
            + "\n"
            + t(
                "Las decides tú en la página de Aprobaciones; yo no puedo aprobarlas.",
                "You decide them on the Approvals page; I cannot approve them.",
            )
        )
    if name == "chat.team":
        lines = [f"{a['name']} — {a['role']} [{a['status']}]" for a in result["agents"]]
        return t("Este es el equipo:", "This is the team:") + "\n" + _bullets(lines, "—")
    if name == "chat.search_knowledge":
        lines = [
            f"{h['title']} ({h['kind']}, {h['trust']}): {h['snippet']}" for h in result["results"]
        ]
        return (
            t("Esto encontré en The Brain:", "This is what The Brain has:")
            + "\n"
            + _bullets(
                lines,
                t("No encontré nada relacionado.", "I found nothing related."),
            )
        )
    if name == "chat.propose_task":
        return t(
            f"Preparé una propuesta de tarea «{args.get('title')}» para el proyecto "
            f"{args.get('project_key')}. Revísala y confírmala en la tarjeta para crearla; "
            "no se crea nada sin tu confirmación.",
            f"I prepared a task proposal “{args.get('title')}” for project "
            f"{args.get('project_key')}. Review and confirm the card to create it; nothing is "
            "created without your confirmation.",
        )
    return json.dumps(result)[:500]


def respond_chat(request: ModelRequest) -> ModelResponse:
    messages = request.messages
    last_user = max(i for i, m in enumerate(messages) if m.role == "user")
    text = messages[last_user].content
    es = len(_SPANISH.findall(text)) >= 1
    after = messages[last_user + 1 :]
    if not after:
        planned = _plan(text, request.hints)
        calls = [
            ToolCall(id=f"call_{i}", name=name, arguments=args)
            for i, (name, args) in enumerate(planned)
        ]
        return _reply(request, "", calls)

    issued = {c.id: c for m in after if m.role == "assistant" for c in m.tool_calls}
    parts = []
    for m in after:
        if m.role != "tool" or m.tool_call_id not in issued:
            continue
        call = issued[m.tool_call_id]
        match = _WRAPPED.search(m.content)
        try:
            result = json.loads(match.group(1) if match else m.content)
        except json.JSONDecodeError:
            continue
        parts.append(_compose(call.name, call.arguments, result, es))
    if [c.name for c in issued.values()] == ["chat.overview"] and _PROPOSE.search(text):
        keys = ", ".join(p["key"] for p in request.hints.get("projects") or []) or "—"
        parts.append(
            f"¿Para qué proyecto es? Opciones: {keys}."
            if es
            else f"Which project? Options: {keys}."
        )
    return _reply(request, "\n\n".join(parts) or ("Listo." if es else "Done."))
