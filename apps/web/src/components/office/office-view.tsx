"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ErrorNote } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useLiveRefresh, useTaskEventFeed } from "@/lib/live-events";
import type { Agent, TaskEvent } from "@/lib/types";
import { AgentPanel } from "./agent-panel";
import { COMPLETED_FLASH_MS } from "./model";
import { OfficeFloor } from "./office-2d";

// three.js is only downloaded when the 3D view is actually shown.
const Office3D = dynamic(() => import("./office-3d"), {
  ssr: false,
  loading: () => <div className="flex h-full items-center justify-center text-muted">Loading 3D office…</div>,
});

type Mode = "3d" | "2d";
const STORAGE_KEY = "agent-hq.office-mode";
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function readStored(): Mode | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "3d" || value === "2d" ? value : null;
  } catch {
    return null;
  }
}

type Capabilities = { webgl: boolean; reducedMotion: boolean; stored: Mode | null };
let cached: { key: string; value: Capabilities } | null = null;

function snapshot(): Capabilities {
  const reducedMotion = window.matchMedia(REDUCED_MOTION).matches;
  const stored = readStored();
  const key = `${reducedMotion}|${stored}`;
  if (!cached || cached.key !== key) {
    cached = { key, value: { webgl: cached?.value.webgl ?? hasWebGL(), reducedMotion, stored } };
  }
  return cached.value;
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(REDUCED_MOTION);
  media.addEventListener("change", onChange);
  window.addEventListener("storage", onChange);
  window.addEventListener("office-mode", onChange);
  return () => {
    media.removeEventListener("change", onChange);
    window.removeEventListener("storage", onChange);
    window.removeEventListener("office-mode", onChange);
  };
}

/** 3D by default; 2D when WebGL is missing or reduced motion is preferred, unless overridden. */
function useOfficeMode(): { mode: Mode | null; webgl: boolean; reducedMotion: boolean; setMode: (m: Mode) => void } {
  const caps = useSyncExternalStore(subscribe, snapshot, () => null);
  const setMode = useCallback((m: Mode) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, m);
    } catch {
      // Storage may be unavailable (private mode); the choice then lasts for this view only.
    }
    window.dispatchEvent(new Event("office-mode"));
  }, []);
  if (!caps) return { mode: null, webgl: false, reducedMotion: false, setMode };
  const fallback: Mode = caps.webgl && !caps.reducedMotion ? "3d" : "2d";
  const mode = caps.stored === "3d" && !caps.webgl ? "2d" : (caps.stored ?? fallback);
  return { mode, webgl: caps.webgl, reducedMotion: caps.reducedMotion, setMode };
}

export function OfficeView() {
  const router = useRouter();
  const agents = useApi<Agent[]>("/agents");
  const [selected, setSelected] = useState<string | null>(null);
  const [completed, setCompleted] = useState<ReadonlySet<string>>(() => new Set());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const { mode, webgl, reducedMotion, setMode } = useOfficeMode();

  useLiveRefresh(agents.reload);
  // Completion feedback comes only from real execution_finished events.
  const onEvent = useCallback((event: TaskEvent) => {
    if (event.type === "execution_finished" && event.payload.status === "succeeded" && event.agent_key) {
      const key = event.agent_key;
      setCompleted((prev) => new Set(prev).add(key));
      clearTimeout(timers.current.get(key));
      timers.current.set(
        key,
        setTimeout(() => {
          setCompleted((prev) => {
            const next = new Set(prev);
            next.delete(key);
            return next;
          });
        }, COMPLETED_FLASH_MS),
      );
    }
  }, []);
  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((t) => clearTimeout(t));
  }, []);
  useTaskEventFeed(null, onEvent);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Live status from real executions.{" "}
          {mode === "3d" ? "Drag to orbit, right-drag to pan, scroll to zoom. Click a department or an agent." : ""}
        </p>
        <div role="group" aria-label="Office view" className="flex rounded-md border border-border text-sm">
          {(["3d", "2d"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              disabled={m === "3d" && !webgl}
              aria-pressed={mode === m}
              title={m === "3d" && !webgl ? "WebGL is not available in this browser" : undefined}
              className={`px-3 py-1 uppercase disabled:opacity-40 ${mode === m ? "bg-surface text-cyan" : "text-muted"}`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      <ErrorNote message={agents.error} />
      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div>
          {mode === "3d" && agents.data && (
            <div className="h-[34rem] overflow-hidden rounded-xl border border-border">
              <Office3D
                agents={agents.data}
                completed={completed}
                selected={selected}
                onSelect={setSelected}
                onOpenBrain={() => router.push("/knowledge")}
                animate={!reducedMotion}
              />
            </div>
          )}
          {mode === "2d" && agents.data && (
            <OfficeFloor agents={agents.data} selected={selected} onSelect={setSelected} completed={completed} />
          )}
          {mode === null && <div className="h-[34rem] rounded-xl border border-border" />}
        </div>
        <div className="flex flex-col gap-3">
          {/* Keyboard-accessible team list; mirrors selection in either view. */}
          <nav aria-label="Team" className="rounded-lg border border-border bg-surface p-2">
            <ul className="flex flex-col">
              {agents.data?.map((a) => (
                <li key={a.key}>
                  <button
                    onClick={() => setSelected(a.key)}
                    aria-current={selected === a.key}
                    className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm ${selected === a.key ? "bg-background text-cyan" : "hover:bg-background"}`}
                  >
                    <span>{a.display_name}</span>
                    <span className="font-mono text-[11px] text-muted">{a.status.replace("_", " ")}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          {selected && <AgentPanel agentKey={selected} onClose={() => setSelected(null)} />}
        </div>
      </div>
    </div>
  );
}
