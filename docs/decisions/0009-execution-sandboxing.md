# ADR-0009: Code/shell execution sandboxing

Status: Proposed (decide in Sprint 2, before QA/Software Engineer agents run code)

## Context
Software Engineer and QA agents will need to run tests and builds on untrusted code.
Running them inside the worker process or on the developer's host is not acceptable.

## Options under evaluation
1. Ephemeral Docker containers launched by a narrow "sandbox runner" service: no network
   by default, read-only base image, tmpfs workspace, CPU/memory/pids/time limits,
   non-root, `no-new-privileges`, no Docker socket inside the sandbox.
2. Option 1 with the gVisor (`runsc`) runtime for stronger isolation.
3. A managed remote sandbox service.

## Constraint already fixed
The worker never receives the Docker socket. Only the sandbox runner does, and it exposes
a minimal allowlisted API (`run(image, command_template_id, workspace_ref, limits)`),
not arbitrary commands.
