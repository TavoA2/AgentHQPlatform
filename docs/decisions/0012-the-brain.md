# ADR-0012: The Brain — scoped, versioned knowledge with provenance

Status: Accepted (Sprint 3)

## Context
Agents need company and project knowledge (services, policies, requirements, past
decisions) without a global memory that anyone can rewrite, without leaking one client's
data into another project, and without treating agent output as established fact.

## Decisions

1. **Two scopes, one table.** `knowledge_documents` holds `company` documents
   (`project_id` NULL) and `project` documents (`project_id` required, enforced by a CHECK).
   Execution memory is stored as project documents of kind `execution_summary`, written
   automatically when a task completes.
2. **Trust is explicit.** Every document is `approved` (written or approved by a human),
   `unverified` (written by an agent, awaiting review), `rejected` or `archived`. Agents see
   the trust label next to every snippet; prompts tell them unverified content is not fact.
3. **Agents propose, humans decide.** Agents may only create `unverified` documents in the
   project of the task they are working on (`knowledge.propose`). They cannot edit, approve,
   archive or write company knowledge. Humans create and edit through the API/UI.
4. **Versioning and provenance.** Each change writes an immutable
   `knowledge_document_versions` row (title, content, trust, author user/agent, source task,
   note). The document row keeps the current content for search. Every change is audited.
5. **Access is filtered in SQL.** Agent reads (`knowledge.search`, CIO context) only return
   company documents plus documents of the *current task's* project, excluding rejected and
   archived ones, and honouring an optional `audience` list of agent keys (e.g. pricing
   visible only to the CIO). Project ids always come from the task context, never from the
   model.
6. **No credentials in knowledge.** Content with credential-like strings is refused for
   both humans and agents (knowledge is separate from secrets).
7. **Retrieval: PostgreSQL full-text search.** A generated `tsvector` (`simple`
   configuration, so Spanish and English both work without stemming) with a GIN index,
   ranked with `ts_rank` and `websearch_to_tsquery`. Semantic/vector retrieval is deferred
   until an evaluation shows full-text is insufficient (no vector database yet).
8. **Retrieved content is untrusted input** and is wrapped like tool output in prompts.

## Consequences
Knowledge stays small, reviewable and auditable. Search is keyword-based; synonyms and
paraphrases may be missed until semantic retrieval is justified.
