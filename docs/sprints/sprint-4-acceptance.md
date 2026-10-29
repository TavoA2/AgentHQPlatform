# Sprint 4 — Interactive 3D Office: Acceptance Criteria and Evidence

Goal: a premium, dark, low-poly isometric office that visualizes the real state of the
agent team and lets the owner navigate to the underlying work. It never invents work,
progress or completions.

Verified on 2026-10-28: 172 backend tests (including the real Docker sandbox test), web
lint/typecheck/build, and a visual check in a real browser against the running stack,
driven by real tasks (no client-side simulation).

## Scene

| Criterion | Status | Evidence |
|---|---|---|
| Dark navy, low-poly, neon cyan/violet/blue/orange | ✅ | `components/office/office-3d.tsx` (primitives only) |
| Department spaces with desks and screens, meeting area, central Brain | ✅ | Executive, Engineering, Quality; round meeting table; animated Brain (click → Brain page) |
| One character per registered agent, no placeholders | ✅ | Placement from `/agents`; unknown departments get their own space |

## Live status

| Criterion | Status | Evidence |
|---|---|---|
| IDLE standing / RUNNING at desk / WAITING_APPROVAL indicator / FAILED indicator | ✅ | `visualFor()` in `model.ts`; browser check showed Dixon with the orange "!" while waiting |
| COMPLETED brief feedback only from `execution_finished` (succeeded) | ✅ | Browser check: QA showed the green ring when its real execution finished |
| Updates via SSE, no simulation | ✅ | Office updated live without reload during a real task |

## Interaction

| Criterion | Status | Evidence |
|---|---|---|
| Orbit/pan/zoom within limits; smooth focus on department | ✅ | OrbitControls distance/polar limits, clamped pan target, eased camera glide |
| Agent detail panel: status, current task, history, links, approvals | ✅ | `agent-panel.tsx` + `GET /agents/{key}` (`test_agent_detail_reflects_real_activity`) |

## Accessibility and fallback

| Criterion | Status | Evidence |
|---|---|---|
| Automatic 2D when WebGL missing or reduced motion preferred; remembered toggle | ✅ | `useOfficeMode()` (WebGL probe, `prefers-reduced-motion`, localStorage) |
| Panel and navigation work in 2D and by keyboard | ✅ | Desks are buttons; keyboard team list beside both views |

## Performance

| Criterion | Status | Evidence |
|---|---|---|
| 3D code-split; primitives only; capped DPR; paused when tab hidden | ✅ | `next/dynamic` (ssr: false), `dpr={[1, 1.5]}`, `frameloop="never"` when hidden |

## Fixes found during verification

- **SSE was buffered behind gzip** in browsers (Next.js compresses responses when the
  client accepts gzip). The stream now sends `Cache-Control: no-cache, no-transform`, so
  no intermediary compresses or buffers it. Verified with a gzip-accepting client.
- **API reload/shutdown hung on open SSE streams.** `agent-hq serve` now uses a 5 s
  graceful-shutdown timeout.

## Known limitations

- RUNNING is often too brief to see with the instant mock provider; real models make it
  visible for longer.
- No automated visual/regression tests for the 3D scene yet (manual browser check).
- The conversational assistant (chat with Dixon, voice, WhatsApp) remains deferred.
