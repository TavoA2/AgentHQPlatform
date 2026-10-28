"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { TaskEvent } from "@/lib/types";

type Listener = (event: TaskEvent) => void;
type LiveEvents = { subscribe: (fn: Listener) => () => void; connected: boolean };

const LiveEventsContext = createContext<LiveEvents>({
  subscribe: () => () => undefined,
  connected: false,
});

/**
 * One EventSource for the whole app. The browser reconnects automatically and sends
 * Last-Event-ID, and the API replays anything missed, so views never drift from the backend.
 */
export function LiveEventsProvider({ children }: { children: React.ReactNode }) {
  const listeners = useRef(new Set<Listener>());
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = new EventSource("/api/events/stream");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("task_event", (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as TaskEvent;
      listeners.current.forEach((fn) => fn(event));
    });
    return () => source.close();
  }, []);

  const subscribe = useCallback((fn: Listener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return (
    <LiveEventsContext.Provider value={{ subscribe, connected }}>{children}</LiveEventsContext.Provider>
  );
}

export function useLiveConnection(): boolean {
  return useContext(LiveEventsContext).connected;
}

/** Calls `reload` (debounced) whenever a matching event arrives. */
export function useLiveRefresh(reload: () => void, filter?: (event: TaskEvent) => boolean) {
  const { subscribe } = useContext(LiveEventsContext);
  const filterRef = useRef(filter);
  const reloadRef = useRef(reload);

  useEffect(() => {
    filterRef.current = filter;
    reloadRef.current = reload;
  });

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = subscribe((event) => {
      if (filterRef.current && !filterRef.current(event)) return;
      clearTimeout(timer);
      timer = setTimeout(() => reloadRef.current(), 250);
    });
    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, [subscribe]);
}

/** Collects events for one task as they stream in. */
export function useTaskEventFeed(taskId: string, onEvent: (event: TaskEvent) => void) {
  const { subscribe } = useContext(LiveEventsContext);
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  });
  useEffect(
    () =>
      subscribe((event) => {
        if (event.task_id === taskId) handler.current(event);
      }),
    [subscribe, taskId],
  );
}
