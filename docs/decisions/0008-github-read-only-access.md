# ADR-0008: Read-only GitHub access for Sprint 1

Status: Accepted (Sprint 0)

## Decision
- Sprint 1 uses a **fine-grained personal access token** limited to explicitly selected
  repositories with *Contents: read*, *Metadata: read* and optionally *Actions: read*
  (workflow runs). Stored as a secret, never in the database.
- Each project lists its authorized repositories in an `Integration` record
  (`provider=github`, `config.allowed_repos=["owner/name"]`). Tools refuse any repository
  not on the project's allowlist, regardless of what the model requests.
- Access is through the GitHub REST API only (list tree, read file, list workflow runs).
  No `git clone` and no code execution in Sprint 1.
- File reads are size-capped and path-filtered (`.github/workflows/**`, `Dockerfile*`,
  `docker-compose*`, build manifests). Contents are treated as untrusted input.
- Migration to a GitHub App (short-lived installation tokens) is planned for Sprint 5,
  before any write scope is granted.

## Consequences
Minimal blast radius if the token leaks (read-only, selected repositories).
