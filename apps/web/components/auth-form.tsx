"use client";
import Link from "next/link";
import { useEffect, useState, FormEvent } from "react";

import { api, Me, setCSRF } from "@/lib/api";
import { Feedback } from "./ui";
const titles = {
  login: "Welcome back.",
  register: "Create your account.",
  recovery: "Recover access.",
  "reset-password": "Set a new password.",
  "accept-invitation": "Join your institution.",
};
export function AuthForm({ mode }: { mode: keyof typeof titles }) {
  const [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [token, setToken] = useState(""),
    [ready, setReady] = useState(false);

  useEffect(() => {
    const t =
      new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    setToken(t);
    if (t) window.history.replaceState(null, "", window.location.pathname);
    if (mode !== "accept-invitation") setReady(true);
    if (mode === "accept-invitation") {
      api<Me>("/auth/me")
        .then((m) => {
          setCSRF(m.csrf);
          setReady(true);
        })
        .catch(() =>
          setError(
            "Sign in or register in another tab, then reopen the invitation link.",
          ),
        );
    }
  }, [mode]);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (mode === "login") {
        const me = await api<Me>("/auth/login", "POST", data);
        setCSRF(me.csrf);
        window.location.assign("/workspaces");
      }
      if (mode === "register") {
        const r = await api<{ message: string }>(
          "/auth/register",
          "POST",
          data,
        );
        setMessage(r.message);
      }
      if (mode === "recovery") {
        const r = await api<{ message: string }>(
          "/auth/recovery",
          "POST",
          data,
        );
        setMessage(r.message);
      }
      if (mode === "reset-password") {
        const r = await api<{ message: string }>(
          "/auth/reset-password",
          "POST",
          { ...data, token },
        );
        setMessage(r.message);
      }
      if (mode === "accept-invitation") {
        await api("/invitations/accept", "POST", { token });
        window.location.assign("/workspaces");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <header className="public-header">
        <Link href="/" className="brand">
          PLUTO<small>BY VOGON</small>
        </Link>
        <span className="mono">Core platform / 01</span>
      </header>
      <main className="auth-layout">
        <section className="auth-story">
          <span className="eyebrow">Institutional intelligence</span>
          <h1>
            Clarity begins
            <br />
            with structure.
          </h1>
          <p className="muted">
            One identity. Authorized workspaces.
            <br />A considered foundation for your institution’s data.
          </p>
          <div className="rule" />
          <span className="mono">PLUTO — Developed by VOGON</span>
        </section>
        <section className="auth-box">
          <span className="eyebrow">Account access</span>
          <h1>{titles[mode]}</h1>
          <p className="muted">
            {mode === "accept-invitation"
              ? "Accept using the account matching your invited email address."
              : mode === "recovery"
                ? "We’ll send a single-use recovery link if an account exists."
                : "Use your institutional email to continue."}
          </p>
          <form onSubmit={submit} className="stack section">
            <Feedback error={error} message={message} />
            {mode === "register" && (
              <label>
                Full name
                <input
                  name="name"
                  required
                  maxLength={120}
                  autoComplete="name"
                />
              </label>
            )}
            {["login", "register", "recovery"].includes(mode) && (
              <label>
                Email address
                <input
                  type="email"
                  name="email"
                  required
                  autoComplete="email"
                />
              </label>
            )}
            {["login", "register", "reset-password"].includes(mode) && (
              <label>
                Password
                <input
                  type="password"
                  aria-label="Password"
                  name="password"
                  required
                  minLength={mode === "login" ? 1 : 12}
                  maxLength={128}
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
                />
                {mode !== "login" && (
                  <span className="muted">At least 12 characters.</span>
                )}
              </label>
            )}
            <button disabled={busy || !ready}>
              {busy
                ? "Please wait…"
                : mode === "login"
                  ? "Sign in →"
                  : mode === "register"
                    ? "Create account"
                    : mode === "recovery"
                      ? "Send recovery link"
                      : mode === "reset-password"
                        ? "Reset password"
                        : "Accept invitation"}
            </button>
            <div className="row between">
              <Link
                className="text-link fine"
                href={mode === "login" ? "/register" : "/login"}
              >
                {mode === "login" ? "Create an account" : "Sign in"}
              </Link>
              {mode === "login" && (
                <Link className="text-link fine" href="/recovery">
                  Forgot password?
                </Link>
              )}
            </div>
          </form>
        </section>
      </main>
    </>
  );
}
