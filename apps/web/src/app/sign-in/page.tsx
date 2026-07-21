"use client";

import { useState, type FormEvent } from "react";

import { accountApi, getErrorMessage } from "@/lib/api-client";

type Mode = "signin" | "signup" | "reset";

export default function SignInPage() {
  const [mode, setMode] = useState<Mode>("signin");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setMessage(null);
    try {
      const email = String(data.get("email") ?? "");
      if (mode === "reset") {
        const result = await accountApi.requestReset(email);
        setMessage(
          result.developmentToken
            ? `Development reset token: ${result.developmentToken}`
            : "If an account exists, a reset link has been sent.",
        );
        return;
      }
      const password = String(data.get("password") ?? "");
      if (mode === "signup") {
        await accountApi.signUp({
          email,
          password,
          displayName: String(data.get("displayName") ?? ""),
        });
      } else {
        await accountApi.signIn({ email, password });
      }
      window.location.assign("/");
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="account-shell">
      <section className="account-card">
        <div className="account-card__eyebrow">SolarPlexus Mobius</div>
        <h1>
          {mode === "signup"
            ? "Create your account"
            : mode === "reset"
              ? "Reset access"
              : "Welcome back"}
        </h1>
        <p>
          {mode === "reset"
            ? "Enter your email and we’ll send a time-limited reset link."
            : "Your canvases, documents, evidence, and Trace records stay isolated to your account."}
        </p>
        <form onSubmit={submit} className="account-form">
          {mode === "signup" && (
            <label>
              Display name
              <input
                name="displayName"
                required
                minLength={1}
                maxLength={120}
                autoComplete="name"
              />
            </label>
          )}
          <label>
            Email
            <input name="email" type="email" required autoComplete="email" />
          </label>
          {mode !== "reset" && (
            <label>
              Password
              <input
                name="password"
                type="password"
                required
                minLength={12}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />
            </label>
          )}
          {message && (
            <div className="account-message" role="status">
              {message}
            </div>
          )}
          <button type="submit" disabled={busy}>
            {busy
              ? "Working…"
              : mode === "signup"
                ? "Create account"
                : mode === "reset"
                  ? "Send reset link"
                  : "Sign in"}
          </button>
        </form>
        <div className="account-links">
          <button type="button" onClick={() => setMode(mode === "signup" ? "signin" : "signup")}>
            {mode === "signup" ? "Already have an account?" : "Create an account"}
          </button>
          <button type="button" onClick={() => setMode(mode === "reset" ? "signin" : "reset")}>
            {mode === "reset" ? "Back to sign in" : "Forgot password?"}
          </button>
        </div>
      </section>
    </main>
  );
}
