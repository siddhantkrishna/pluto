"use client";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Workspace, Institution } from "@/lib/api";
import { Empty, Feedback, Modal } from "./ui";
export function WorkspaceSelector() {
  const [items, setItems] = useState<Workspace[] | null>(null),
    [error, setError] = useState(""),
    [create, setCreate] = useState(false),
    [busy, setBusy] = useState(false);
  const router = useRouter();
  useEffect(() => {
    api<Workspace[]>("/institutions")
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const institution = await api<Institution>(
        "/institutions",
        "POST",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      router.push(`/workspace/${institution.id}/overview`);
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
          <span className="eyebrow">Your institutions</span>
          <h1>Choose your workspace.</h1>
          <p className="muted">
            Each institution has its own people, catalog, and access controls.
          </p>
        </div>
        <button disabled={items === null} onClick={() => setCreate(true)}>
          + Create institution
        </button>
      </div>
      <Feedback error={error} />
      {items === null ? (
        <div className="loading" role="status">
          Loading workspaces…
        </div>
      ) : items.length === 0 ? (
        <Empty title="Your first workspace starts here.">
          Create an institution to organize its data catalog, or accept an
          invitation from your team.
        </Empty>
      ) : (
        items.map((w) => (
          <article key={w.institution.id} className="card workspace-card">
            <div>
              <span className="mono">Institution / {w.institution.status}</span>
              <h2 className="section">{w.institution.name}</h2>
              <span className="badge">{w.role}</span>
            </div>
            {w.institution.status === "active" ? (
              <Link
                className="button secondary"
                href={`/workspace/${w.institution.id}/overview`}
              >
                Open workspace ↗
              </Link>
            ) : (
              <p className="muted">Contact your platform administrator.</p>
            )}
          </article>
        ))
      )}
      {create && (
        <Modal title="Create institution" onClose={() => setCreate(false)}>
          <form onSubmit={submit} className="stack">
            <p>You will become the institution’s first owner.</p>
            <label>
              Institution name
              <input name="name" required maxLength={160} />
            </label>
            <Feedback error={error} />
            <button disabled={busy}>
              {busy ? "Creating…" : "Create workspace"}
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}
