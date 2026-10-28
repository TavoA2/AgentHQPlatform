# Sprint 3 — The Brain: Acceptance Criteria and Evidence

Goal: agents work with scoped, trustworthy company and project knowledge; humans control
what becomes fact; every piece of knowledge has provenance and history.

Verified on 2026-10-28: 171 backend tests passing against PostgreSQL 17 (including the
real Docker sandbox test), lint/mypy clean, web lint/typecheck/build passing, migration
upgrade → downgrade → upgrade with no model drift, and an end-to-end run of the full
Compose stack (knowledge created → Dixon used 2 entries → task COMPLETED → execution
summary stored as unverified → audit chain OK).

## Knowledge

| Criterion | Status | Evidence |
|---|---|---|
| Humans create, edit (new version), approve, reject, archive; versioned and audited | ✅ | `test_human_documents_are_approved_versioned_and_audited`, `test_human_review_promotes_agent_knowledge` |
| Version history is immutable | ✅ | DB trigger; same test (`append-only`) |
| Agents only propose `unverified` documents in their task's project | ✅ | `test_agents_only_propose_unverified_project_knowledge` |
| Completed task writes an unverified `execution_summary` linked to it | ✅ | `test_dixon_uses_knowledge_and_remembers_outcomes`; E2E |
| Content with credentials refused (humans and agents) | ✅ | `test_credentials_are_refused`; propose test |

## Access and isolation

| Criterion | Status | Evidence |
|---|---|---|
| Agent on project A never retrieves project B documents | ✅ | `test_agents_never_see_other_projects` (also ignores an injected `project_id`) |
| `audience` restricts documents to specific agents | ✅ | `test_audience_and_trust_filter_agent_reads` |
| Rejected/archived documents never retrieved by agents | ✅ | Same test |
| Agents cannot write company knowledge or approve | ✅ | Propose test: scope/trust arguments ignored; `knowledge.approve` denied |

## Retrieval

| Criterion | Status | Evidence |
|---|---|---|
| Full-text search ranks relevant documents in Spanish and English | ✅ | `test_search_ranks_spanish_and_english` |
| Dixon's analysis includes relevant knowledge with trust labels, wrapped as untrusted | ✅ | `test_dixon_uses_knowledge_and_remembers_outcomes`; `knowledge_used` recorded on the analyze step |
| Specialists can search knowledge through the policy-checked tool | ✅ | `test_specialists_can_search_knowledge` |

## UI and other

| Criterion | Status | Evidence |
|---|---|---|
| Brain page: search/filters, create/edit, review unverified, history, provenance | ✅ | `apps/web/src/app/(app)/knowledge` |
| CIO presented as "Dixon" | ✅ | `test_cio_is_presented_as_dixon`; E2E agent list |

## Known limitations

- Keyword (full-text) retrieval only; synonyms and paraphrases may be missed. Semantic
  search is deferred until evaluation shows the need (ADR-0012).
- Only humans can edit documents; agents can propose new ones but not suggest edits yet.
- The conversational assistant (chat with Dixon, proactive alerts, voice, WhatsApp) is
  deferred by the owner to a later sprint.
- Real-model behaviour is still unverified (no OpenAI API credit); all runs used the mock.
