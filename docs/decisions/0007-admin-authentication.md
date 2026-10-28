# ADR-0007: Admin authentication — password + server-side sessions

Status: Accepted (Sprint 0)

## Decision
- Single administrator for the MVP, stored in `users` with an **Argon2id** password hash.
- Created by a CLI command (`agent-hq create-admin`) that prompts for the password; no
  plaintext admin password in environment files.
- Server-side sessions table (random 256-bit token, stored hashed), sliding expiry
  (12 h idle, 7 d absolute). Cookie: `HttpOnly`, `Secure` (except localhost),
  `SameSite=Lax`.
- The browser reaches the API through the Next.js same-origin proxy, so CORS stays
  closed. State-changing requests require a CSRF token (double-submit) and a matching
  `Origin`.
- Login rate limit per IP and per account with backoff; generic error messages.
- Users carry a `role` column (`admin` now) so multi-user/RBAC can be added without a
  schema redesign. TOTP 2FA is planned before any cloud exposure (Sprint 6).

## Consequences
No dependency on an external identity provider. Must be paired with TLS when deployed.
