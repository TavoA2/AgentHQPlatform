"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

// All calls go to the same-origin /api proxy (next.config.ts); the browser never talks to
// the backend, model providers or integrations directly.

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function csrfToken(): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("agent_hq_csrf="))
    ?.split("=")[1];
}

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d)))
        .join("; ");
    }
  }
  return fallback;
}

export async function api<T>(
  path: string,
  init: { method?: "GET" | "POST" | "PUT" | "DELETE"; body?: unknown } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    credentials: "same-origin",
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, res.statusText));
  return data as T;
}

type QueryState<T> = { data?: T; error?: string; loading: boolean };

/** Fetches `path` (null = skip) and exposes `reload` for live refreshes. */
export function useApi<T>(path: string | null) {
  const [state, setState] = useState<QueryState<T>>({ loading: path !== null });
  const [version, setVersion] = useState(0);
  const router = useRouter();

  useEffect(() => {
    if (path === null) return;
    let active = true;
    api<T>(path)
      .then((data) => {
        if (active) setState({ data, loading: false });
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
          return;
        }
        setState((s) => ({ ...s, error: err instanceof Error ? err.message : String(err), loading: false }));
      });
    return () => {
      active = false;
    };
  }, [path, version, router]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload };
}
