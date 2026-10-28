# ADR-0005: Model provider abstraction and model profiles

Status: Accepted (Sprint 0)

## Decision
- An internal `ChatModelProvider` protocol (`invoke` with typed messages, tool schemas
  and a structured-output schema; returns content, tool calls and token usage).
  Implementations: `mock` (deterministic, scripted responses for tests), `openai`
  (Sprint 1), `anthropic` (later). LangChain chat model classes may be used inside an
  adapter, not throughout the codebase.
- Agents reference **profiles** (`reasoning`, `fast`, …). Configuration maps
  `profile → provider:model`, with overrides per agent and per task. Model names appear
  only in configuration.
- API keys are read from secrets (env locally) by the provider adapter only.
- Every call records provider, model, input/output tokens, latency and estimated cost on
  the `TaskExecution`; per-task and daily budget limits stop execution when exceeded.

## Consequences
Switching providers is a configuration change. A ChatGPT consumer subscription does not
include API usage; real runs need an OpenAI API key with billing.
