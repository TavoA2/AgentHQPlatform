"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ErrorNote, inputClass } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { brandName } from "@/lib/brand";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  // Shown once the API confirms the password and asks for the authenticator code.
  const [needsCode, setNeedsCode] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(undefined);
    try {
      await api("/auth/login", {
        method: "POST",
        body: {
          email: form.get("email"),
          password: form.get("password"),
          otp: needsCode ? form.get("otp") : undefined,
        },
      });
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && err.message === "otp_required") {
        setNeedsCode(true);
      } else {
        setError(err instanceof Error ? err.message : "Sign-in failed");
      }
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-6 px-4 py-16">
      <header>
        <p className="font-mono text-xs uppercase tracking-widest text-violet">{brandName}</p>
        <h1 className="mt-1 text-2xl font-semibold">Agent HQ</h1>
        <p className="mt-1 text-sm text-muted">Administrator sign-in</p>
      </header>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Email
          <input name="email" type="email" autoComplete="username" required className={inputClass} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className={inputClass}
          />
        </label>
        {needsCode && (
          <label className="flex flex-col gap-1 text-sm">
            Authenticator code
            <input
              name="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              maxLength={6}
              required
              autoFocus
              className={`${inputClass} font-mono tracking-[0.4em]`}
            />
          </label>
        )}
        <ErrorNote message={error} />
        <Button type="submit" disabled={busy}>
          {busy ? "Signing in…" : needsCode ? "Verify" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}
