"use client";
import { FormEvent, useEffect, useState } from "react";
import { api, Session } from "@/lib/api";
import { useIdentity } from "./shell";
import { Confirm, Feedback, date } from "./ui";
export function Account() {
  const me = useIdentity();
  const [sessions, setSessions] = useState<Session[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [revoke, setRevoke] = useState<string>();
  function load() {
    api<Session[]>("/users/sessions")
      .then(setSessions)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        "/users/password",
        "POST",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      window.location.href = "/login";
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Personal settings</span>
          <h1>Account & security</h1>
          <p className="muted">Manage your identity and active sessions.</p>
        </div>
      </div>
      <Feedback error={error} />
      <div className="account-grid">
        <section className="card">
          <span className="mono">Identity</span>
          <h2 className="section">{me.user.name}</h2>
          <p>{me.user.email}</p>
          <span className="badge">{me.user.status}</span>
          <p className="muted fine">
            Account created {date(me.user.created_at)}
          </p>
        </section>
        <form className="card stack" onSubmit={submit}>
          <h2>Change password</h2>
          <label>
            Current password
            <input
              type="password"
              name="current_password"
              autoComplete="current-password"
              required
              maxLength={128}
            />
          </label>
          <label>
            New password
            <input
              type="password"
              name="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
              required
            />
          </label>
          <p className="fine muted">
            Use at least 12 characters. Changing your password revokes all
            sessions, including this one.
          </p>
          <button disabled={busy}>
            {busy ? "Updating…" : "Change password"}
          </button>
        </form>
      </div>
      <h2 className="section">Active sessions</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Created</th>
              <th>Expires</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id}>
                <td>{date(s.created_at)}</td>
                <td>{date(s.expires_at)}</td>
                <td>
                  <button className="secondary" onClick={() => setRevoke(s.id)}>
                    Revoke session
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {revoke && (
        <Confirm
          title="Revoke this session?"
          onClose={() => setRevoke(undefined)}
          onConfirm={async () => {
            await api(`/users/sessions/${revoke}`, "DELETE");
            try {
              await api("/auth/me");
              load();
            } catch {
              window.location.href = "/login";
            }
          }}
        />
      )}
    </>
  );
}
