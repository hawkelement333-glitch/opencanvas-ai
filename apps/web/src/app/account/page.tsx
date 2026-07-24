"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { accountApi, getErrorMessage } from "@/lib/api-client";

export default function AccountPage() {
  const account = useQuery({
    queryKey: ["account"],
    queryFn: ({ signal }) => accountApi.me(signal),
  });
  const [message, setMessage] = useState<string | null>(null);

  async function update(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const displayName = String(new FormData(event.currentTarget).get("displayName") ?? "");
    try {
      await accountApi.update({ displayName });
      await account.refetch();
      setMessage("Account settings saved.");
    } catch (error) {
      setMessage(getErrorMessage(error));
    }
  }

  if (account.isPending)
    return (
      <main className="account-shell">
        <p role="status">Loading account…</p>
      </main>
    );
  if (account.isError)
    return (
      <main className="account-shell">
        <section className="account-card" aria-labelledby="account-session-title">
          <h1 id="account-session-title">Session expired</h1>
          <p>{getErrorMessage(account.error)}</p>
          <a href="/sign-in">Sign in again</a>
        </section>
      </main>
    );

  return (
    <main className="account-shell">
      <section className="account-card account-card--wide" aria-labelledby="account-title">
        <div className="account-card__eyebrow">Account settings</div>
        <h1 id="account-title">{account.data.displayName}</h1>
        <p className="account-card__identity">{account.data.email}</p>
        <form onSubmit={update} className="account-form">
          <label>
            Display name
            <input name="displayName" defaultValue={account.data.displayName} required />
          </label>
          <button type="submit">Save settings</button>
        </form>
        <div className="account-actions">
          <button
            type="button"
            onClick={async () => {
              await accountApi.requestExport();
              setMessage("Your data export has been queued.");
            }}
          >
            Request data export
          </button>
          <button
            type="button"
            onClick={async () => {
              await accountApi.signOut();
              window.location.assign("/sign-in");
            }}
          >
            Sign out
          </button>
          <Link href="/">Back to workspace</Link>
        </div>
        {message && (
          <div className="account-message" role="status">
            {message}
          </div>
        )}
      </section>
    </main>
  );
}
