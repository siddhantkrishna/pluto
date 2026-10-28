"use client";
import { FormEvent, useEffect, useState } from "react";
import { api, Page, Institution, User, Audit } from "@/lib/api";
import { useIdentity } from "./shell";
import { Confirm, Empty, Feedback, Modal, Pagination, date } from "./ui";
import { AuditTable } from "./workspace-page";
export function Platform() {
  const me = useIdentity();
  const [tab, setTab] = useState("institutions"),
    [institutions, setInstitutions] = useState<Institution[]>([]),
    [users, setUsers] = useState<User[]>([]),
    [events, setEvents] = useState<Audit[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [q, setQ] = useState(""),
    [search, setSearch] = useState(""),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [version, setVersion] = useState(0),
    [adding, setAdding] = useState(false),
    [busy, setBusy] = useState(false),
    [confirm, setConfirm] = useState<{
      title: string;
      run: () => Promise<void>;
    }>();
  function refresh() {
    setVersion((v) => v + 1);
  }
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    async function load() {
      try {
        const params = new URLSearchParams({
          offset: String(offset),
          q: search,
        });
        if (tab === "institutions") {
          const r = await api<Page<Institution>>(
            `/platform/institutions?${params}`,
          );
          if (active) {
            setInstitutions(r.items);
            setTotal(r.total);
          }
        }
        if (tab === "users") {
          const r = await api<Page<User>>(`/platform/users?${params}`);
          if (active) {
            setUsers(r.items);
            setTotal(r.total);
          }
        }
        if (tab === "administrators") {
          const r = await api<User[]>("/platform/administrators");
          if (active) setUsers(r);
        }
        if (tab === "audit") {
          const r = await api<Page<Audit>>(`/platform/audit?${params}`);
          if (active) {
            setEvents(r.items);
            setTotal(r.total);
          }
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    }
    if (me.platform_admin) void load();
    return () => {
      active = false;
    };
  }, [tab, offset, search, version, me.platform_admin]);
  function action(title: string, path: string, method: string, body?: unknown) {
    setConfirm({
      title,
      run: async () => {
        await api(path, method, body);
        refresh();
      },
    });
  }
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        "/platform/administrators",
        "POST",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      setAdding(false);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!me.platform_admin)
    return (
      <Empty title="Platform administrator access required.">
        Your account is not authorized for installation administration.
      </Empty>
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">VOGON / Installation administration</span>
          <h1>Platform control</h1>
          <p className="muted">
            Institution lifecycle and operational metadata. Customer catalogs
            remain within their authorized workspaces.
          </p>
        </div>
      </div>
      <div className="row" role="tablist" aria-label="Platform sections">
        {["institutions", "users", "administrators", "audit"].map((t) => (
          <button
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "" : "secondary"}
            key={t}
            onClick={() => {
              setTab(t);
              setOffset(0);
              setSearch("");
              setQ("");
            }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <Feedback error={error} />
      {["institutions", "users"].includes(tab) && (
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            setSearch(q);
          }}
        >
          <input
            aria-label="Search platform records"
            placeholder={
              tab === "users" ? "Search email…" : "Search institutions…"
            }
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="secondary">Search</button>
        </form>
      )}
      {tab === "administrators" && (
        <button className="section" onClick={() => setAdding(true)}>
          + Add administrator
        </button>
      )}
      {loading ? (
        <div className="loading" role="status">
          Loading platform records…
        </div>
      ) : (
        !error && (
          <div className="section">
            {tab === "institutions" &&
              (institutions.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Institution</th>
                        <th>Status</th>
                        <th>Created</th>
                        <th>Lifecycle</th>
                      </tr>
                    </thead>
                    <tbody>
                      {institutions.map((i) => (
                        <tr key={i.id}>
                          <td>
                            {i.name}
                            <small className="mono">{i.id}</small>
                          </td>
                          <td>
                            <span className="badge">{i.status}</span>
                          </td>
                          <td>{date(i.created_at)}</td>
                          <td>
                            <button
                              className="secondary"
                              onClick={() =>
                                action(
                                  `${i.status === "active" ? "Suspend" : "Reactivate"} ${i.name}?`,
                                  `/platform/institutions/${i.id}`,
                                  "PATCH",
                                  {
                                    status:
                                      i.status === "active"
                                        ? "suspended"
                                        : "active",
                                  },
                                )
                              }
                            >
                              {i.status === "active" ? "Suspend" : "Reactivate"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title="No institutions found.">
                  Institution records will appear when workspaces are created.
                </Empty>
              ))}
            {["users", "administrators"].includes(tab) && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Account</th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td>
                          {u.name}
                          <small>{u.email}</small>
                        </td>
                        <td>{u.status}</td>
                        <td>
                          <button
                            className="secondary"
                            onClick={() =>
                              tab === "administrators"
                                ? action(
                                    `Remove administrator privileges from ${u.name}?`,
                                    `/platform/administrators/${u.id}`,
                                    "DELETE",
                                  )
                                : action(
                                    `${u.status === "active" ? "Disable" : "Activate"} ${u.name}?`,
                                    `/platform/users/${u.id}`,
                                    "PATCH",
                                    {
                                      status:
                                        u.status === "active"
                                          ? "disabled"
                                          : "active",
                                    },
                                  )
                            }
                          >
                            {tab === "administrators"
                              ? "Remove privileges"
                              : u.status === "active"
                                ? "Disable account"
                                : "Activate account"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {tab === "audit" &&
              (events.length ? (
                <AuditTable events={events} />
              ) : (
                <Empty title="No administrative activity yet.">
                  Platform-level administrative actions will be recorded here.
                </Empty>
              ))}
            {tab !== "administrators" && (
              <Pagination total={total} offset={offset} setOffset={setOffset} />
            )}
          </div>
        )
      )}
      {adding && (
        <Modal
          title="Add platform administrator"
          onClose={() => setAdding(false)}
        >
          <form className="stack" onSubmit={add}>
            <Feedback error={error} />
            <p>The person must already have an active PLUTO account.</p>
            <label>
              Account email
              <input name="email" type="email" required />
            </label>
            <button disabled={busy}>
              {busy ? "Saving…" : "Grant administrator access"}
            </button>
          </form>
        </Modal>
      )}
      {confirm && (
        <Confirm
          title={confirm.title}
          onConfirm={confirm.run}
          onClose={() => setConfirm(undefined)}
        />
      )}
    </>
  );
}
