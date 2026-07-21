"use client";

import { useState, type FormEvent } from "react";

import { accountApi, getErrorMessage } from "@/lib/api-client";

export default function ResetPasswordPage() {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const token = new URL(window.location.href).searchParams.get("token") ?? "";
    setBusy(true);
    setMessage(null);
    try {
      await accountApi.confirmReset(token, String(data.get("password") ?? ""));
      window.location.assign("/sign-in");
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
        <h1>Choose a new password</h1>
        <p>Use at least 12 characters with upper- and lowercase letters plus a number.</p>
        <form onSubmit={submit} className="account-form">
          <label>
            New password
            <input
              name="password"
              type="password"
              required
              minLength={12}
              autoComplete="new-password"
            />
          </label>
          {message && (
            <div className="account-message" role="alert">
              {message}
            </div>
          )}
          <button type="submit" disabled={busy}>
            {busy ? "Updating…" : "Update password"}
          </button>
        </form>
      </section>
    </main>
  );
}
