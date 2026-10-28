# ADR-0002: Tooling and dependency version policy

Status: Accepted (Sprint 0)

## Decision
- **Python 3.13** in containers (project supports `>=3.12`). Managed with **uv**;
  `uv.lock` is committed and CI uses `uv sync --locked`.
- Python quality: **ruff** (lint + format), **mypy** (strict on `agent_hq`), **pytest**.
- **Node 24 LTS**, **npm** with committed `package-lock.json`. Next.js (App Router),
  TypeScript strict, Tailwind CSS v4, ESLint. shadcn/ui, TanStack Query and React Three
  Fiber are added in the sprint that first uses them.
- **PostgreSQL 17**.
- Versions are pinned via lockfiles; `pyproject.toml` / `package.json` declare compatible
  ranges. Resolved versions are recorded in [../dependencies.md](../dependencies.md) when
  they change materially. Upgrades are deliberate PRs, not incidental.
- GitHub Actions are referenced by major tag in Sprint 0; pin to commit SHAs before the
  repository gains deploy credentials (Sprint 5–6).

## Consequences
Reproducible installs locally and in CI. Python is not required on the host to run the
stack (Docker), but uv is used on the host for editor tooling and fast tests.
