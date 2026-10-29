"use client";

import { createContext, useContext } from "react";
import type { Session } from "@/lib/types";

const SessionContext = createContext<Session | null>(null);

export const SessionProvider = SessionContext.Provider;

/**
 * False for the read-only viewer of the public demo. Hiding actions is only a courtesy:
 * the API refuses every state change in demo mode regardless (ADR-0013).
 */
export function useCanAct(): boolean {
  const session = useContext(SessionContext);
  return session !== null && session.user.role !== "viewer";
}
