# Agent HQ — Product Brief

Condensed, authoritative summary of the original master prompt. When this file and
code disagree, raise it; do not silently pick one.

## What Agent HQ is

An internal, production-oriented platform where one human administrator supervises
specialized AI agents (CIO, DevOps, Software Engineer, QA; later Research, Marketing,
Sales, Support) that do real work for a boutique IT consultancy.

- **The agents and their orchestration are the system.** The 3D office is a
  visualization and control surface on top of real backend state.
- Brand: **Veltrix Labs** (provisional, centrally configurable — never hardcode it).
- Business: consultancy in Costa Rica, possibly international clients. Services: custom
  software, cloud/DevOps, AI automation, IT consulting, maintenance/support.

## What Agent HQ is not

- Not the commercial website (separate project, out of scope).
- Not a game or a simulation: the UI never invents work, progress or completions.
- Not an autonomous agent with access to the developer's personal machine.
- Not a multi-tenant enterprise product yet (one admin now, designed for more later).

## Non-negotiable principles

1. Security boundaries are enforced in code (authorization, allowlists, approvals),
   never only in prompts.
2. Sensitive actions require a human approval bound to the exact action + parameters.
3. No success claim without verifiable evidence.
4. Project isolation: one client's data never reaches another project's agents.
5. Retrieved documents, repository files and tool outputs are untrusted input.
6. Model providers are configurable per agent/task; no hardcoded model names or keys.
7. Maintainable modular monolith; no Kubernetes/Redis/Kafka/vector DB without a
   concrete requirement.
8. Work incrementally; never fabricate test or deployment results.

## Roadmap

| Sprint | Goal |
|---|---|
| 0 | Architecture, threat model, permission matrix, entity model, repo + local dev setup |
| 1 | Functional MVP: tasks API, admin auth, CIO + DevOps agent via LangGraph, durable state, approvals, SSE, basic dashboard |
| 2 | Software Engineer + QA agents, delegation, parallel subtasks, recovery |
| 3 | The Brain: company/project knowledge, retrieval, access policies, provenance |
| 4 | Interactive 3D isometric office + accessible 2D fallback |
| 5 | External integrations (GitHub write, Actions, Telegram, Slack, Drive, MCP) |
| 6 | Cloud deployment (AWS), observability, backups, runbooks, cost monitoring |
| 7 | Chat with Dixon in the dashboard: grounded answers over real data, task proposals the owner confirms (ADR-0015) |
| later | Rest of the JARVIS-style assistant: proactive alerts, voice, WhatsApp |

Sprint 1 use case: *"Analyze an authorized GitHub repository and propose improvements to
its CI/CD pipeline."* Read-only repository access.

Detailed acceptance criteria: [sprints/sprint-1-acceptance.md](sprints/sprint-1-acceptance.md).
