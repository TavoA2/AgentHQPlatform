"""The Brain: scoped, versioned knowledge with provenance (ADR-0012).

Access rules live here, in SQL filters, and are the same for every caller path:
- humans may read and manage everything;
- agents only see company documents plus documents of the project of the task they are
  working on, never rejected/archived ones, and only documents whose audience includes
  them (empty audience = all agents);
- agents may only *propose* unverified documents in that project.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.domain import KNOWLEDGE_KINDS, DomainError, KnowledgeScope, KnowledgeTrust
from agent_hq.events import record_audit
from agent_hq.logging import contains_credential
from agent_hq.models import KnowledgeDocument, KnowledgeDocumentVersion, utcnow

MAX_CONTENT_CHARS = 50_000
_TOKEN = re.compile(r"[0-9a-záéíóúüñ]{3,}", re.IGNORECASE)
_HEADLINE = "MaxWords=35, MinWords=12, MaxFragments=2, StartSel=«, StopSel=»"


class KnowledgeError(DomainError):
    pass


@dataclass(frozen=True)
class KnowledgeHit:
    document: KnowledgeDocument
    rank: float
    snippet: str

    def for_agent(self) -> dict[str, Any]:
        return {
            "id": str(self.document.id),
            "title": self.document.title,
            "kind": self.document.kind,
            "scope": self.document.scope.value,
            "trust": self.document.trust.value,
            "snippet": self.snippet,
        }


def _validate(kind: str, title: str, content: str) -> None:
    if kind not in KNOWLEDGE_KINDS:
        raise KnowledgeError(f"unknown knowledge kind {kind!r}")
    if not title.strip() or not content.strip():
        raise KnowledgeError("title and content are required")
    if len(content) > MAX_CONTENT_CHARS:
        raise KnowledgeError(f"content exceeds {MAX_CONTENT_CHARS} characters")
    if contains_credential(f"{title}\n{content}"):
        raise KnowledgeError("knowledge must not contain credentials")


def _author(user_id: uuid.UUID | None, agent_key: str | None) -> tuple[str, str]:
    return ("user", str(user_id)) if user_id else ("agent", str(agent_key))


async def _add_version(
    session: AsyncSession,
    doc: KnowledgeDocument,
    *,
    user_id: uuid.UUID | None,
    agent_key: str | None,
    note: str | None,
) -> None:
    session.add(
        KnowledgeDocumentVersion(
            document_id=doc.id,
            version=doc.version,
            title=doc.title,
            content=doc.content,
            trust=doc.trust,
            changed_by_user_id=user_id,
            changed_by_agent=agent_key,
            source_task_id=doc.source_task_id,
            note=note,
        )
    )
    await session.flush()


async def create_document(
    session: AsyncSession,
    *,
    scope: KnowledgeScope,
    project_id: uuid.UUID | None,
    kind: str,
    title: str,
    content: str,
    user_id: uuid.UUID | None = None,
    agent_key: str | None = None,
    source_task_id: uuid.UUID | None = None,
    audience: list[str] | None = None,
    tags: list[str] | None = None,
    note: str | None = None,
) -> KnowledgeDocument:
    _validate(kind, title, content)
    if (scope == KnowledgeScope.PROJECT) != (project_id is not None):
        raise KnowledgeError("project documents need a project; company documents must not")
    if user_id is None and agent_key is None:
        raise KnowledgeError("a document needs an author")
    if agent_key is not None and (user_id is not None or scope != KnowledgeScope.PROJECT):
        raise KnowledgeError("agents may only propose project knowledge")
    doc = KnowledgeDocument(
        scope=scope,
        project_id=project_id,
        kind=kind,
        title=title.strip()[:200],
        content=content.strip(),
        # Humans write facts; anything an agent writes awaits human review.
        trust=KnowledgeTrust.APPROVED if user_id else KnowledgeTrust.UNVERIFIED,
        audience=sorted(set(audience or [])),
        tags=sorted(set(tags or [])),
        created_by_user_id=user_id,
        created_by_agent=agent_key,
        source_task_id=source_task_id,
        reviewed_by=user_id,
        reviewed_at=utcnow() if user_id else None,
    )
    session.add(doc)
    await session.flush()
    await _add_version(session, doc, user_id=user_id, agent_key=agent_key, note=note)
    actor_type, actor_id = _author(user_id, agent_key)
    await record_audit(
        session,
        actor_type=actor_type,  # type: ignore[arg-type]
        actor_id=actor_id,
        action="knowledge.created",
        project_id=project_id,
        resource_type="knowledge",
        resource_id=doc.id,
        details={"title": doc.title, "trust": doc.trust.value, "scope": scope.value},
    )
    return doc


async def update_document(
    session: AsyncSession,
    doc: KnowledgeDocument,
    *,
    user_id: uuid.UUID,
    title: str,
    content: str,
    audience: list[str] | None,
    tags: list[str] | None,
    note: str | None,
) -> KnowledgeDocument:
    """A human edit: new immutable version; the edited content is approved by that human."""
    _validate(doc.kind, title, content)
    doc.title = title.strip()[:200]
    doc.content = content.strip()
    if audience is not None:
        doc.audience = sorted(set(audience))
    if tags is not None:
        doc.tags = sorted(set(tags))
    doc.trust = KnowledgeTrust.APPROVED
    doc.reviewed_by = user_id
    doc.reviewed_at = utcnow()
    doc.version += 1
    await session.flush()
    await _add_version(session, doc, user_id=user_id, agent_key=None, note=note)
    await record_audit(
        session,
        actor_type="user",
        actor_id=str(user_id),
        action="knowledge.updated",
        project_id=doc.project_id,
        resource_type="knowledge",
        resource_id=doc.id,
        details={"version": doc.version, "note": note},
    )
    return doc


async def set_trust(
    session: AsyncSession,
    doc: KnowledgeDocument,
    trust: KnowledgeTrust,
    *,
    user_id: uuid.UUID,
    note: str | None,
) -> KnowledgeDocument:
    """Only humans call this (API); no agent tool maps to it."""
    if doc.trust == trust:
        return doc
    doc.trust = trust
    doc.reviewed_by = user_id
    doc.reviewed_at = utcnow()
    doc.version += 1
    await session.flush()
    await _add_version(session, doc, user_id=user_id, agent_key=None, note=note)
    await record_audit(
        session,
        actor_type="user",
        actor_id=str(user_id),
        action=f"knowledge.{trust.value}",
        project_id=doc.project_id,
        resource_type="knowledge",
        resource_id=doc.id,
        details={"version": doc.version, "note": note},
    )
    return doc


def agent_visibility(project_id: uuid.UUID, agent_key: str) -> ColumnElement[bool]:
    """The only filter used for agent reads: company + current project, readable trust,
    and an audience that includes the agent."""
    return and_(
        or_(
            KnowledgeDocument.scope == KnowledgeScope.COMPANY,
            KnowledgeDocument.project_id == project_id,
        ),
        KnowledgeDocument.trust.in_([KnowledgeTrust.APPROVED, KnowledgeTrust.UNVERIFIED]),
        or_(
            func.cardinality(KnowledgeDocument.audience) == 0,
            KnowledgeDocument.audience.contains([agent_key]),
        ),
    )


def _any_word_query(text: str) -> str | None:
    words = list(dict.fromkeys(w.lower() for w in _TOKEN.findall(text)))[:24]
    return " | ".join(words) if words else None


async def _search(
    session: AsyncSession,
    query: Select[Any],
    *,
    tsquery: Any | None,
    limit: int,
) -> list[KnowledgeHit]:
    if tsquery is None:
        rows = await session.execute(
            query.add_columns(literal(0.0), func.left(KnowledgeDocument.content, 240))
            .order_by(KnowledgeDocument.updated_at.desc())
            .limit(limit)
        )
    else:
        rank = func.ts_rank(KnowledgeDocument.search_vector, tsquery)
        snippet = func.ts_headline("simple", KnowledgeDocument.content, tsquery, _HEADLINE)
        rows = await session.execute(
            query.add_columns(rank, snippet)
            .where(KnowledgeDocument.search_vector.op("@@")(tsquery))
            .order_by(rank.desc(), KnowledgeDocument.updated_at.desc())
            .limit(limit)
        )
    return [KnowledgeHit(doc, float(r), str(s)) for doc, r, s in rows]


async def agent_search(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    agent_key: str,
    text: str,
    limit: int = 5,
) -> list[KnowledgeHit]:
    """Retrieval for agents. Any-word matching suits natural-language requests."""
    words = _any_word_query(text)
    tsquery = func.to_tsquery("simple", words) if words else None
    query = select(KnowledgeDocument).where(agent_visibility(project_id, agent_key))
    return await _search(session, query, tsquery=tsquery, limit=limit)


async def human_search(
    session: AsyncSession,
    *,
    text: str | None,
    scope: KnowledgeScope | None,
    project_id: uuid.UUID | None,
    trust: KnowledgeTrust | None,
    kind: str | None,
    limit: int,
) -> list[KnowledgeHit]:
    query = select(KnowledgeDocument)
    if scope:
        query = query.where(KnowledgeDocument.scope == scope)
    if project_id:
        query = query.where(KnowledgeDocument.project_id == project_id)
    if trust:
        query = query.where(KnowledgeDocument.trust == trust)
    if kind:
        query = query.where(KnowledgeDocument.kind == kind)
    tsquery = func.websearch_to_tsquery("simple", text) if text and text.strip() else None
    return await _search(session, query, tsquery=tsquery, limit=limit)
