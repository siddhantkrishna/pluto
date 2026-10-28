"use client";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  api,
  all,
  Page,
  Dataset,
  Source,
  Member,
  Invitation,
  Audit,
  Workspace,
} from "@/lib/api";
import { CatalogForm, SourceForm } from "./catalog-form";
import { Confirm, Empty, Feedback, Modal, Pagination, date } from "./ui";
const labels: Record<string, string> = {
  overview: "Workspace overview",
  catalog: "Data catalog",
  sources: "Data-source registry",
  members: "People & access",
  invitations: "Invitations",
  settings: "Institution settings",
  audit: "Activity history",
};
const descriptions: Record<string, string> = {
  overview: "Your institutional data foundation, in one place.",
  catalog:
    "Discover, classify, and maintain your institution’s dataset metadata.",
  sources:
    "Define where data will come from. Connectors are not yet available.",
  members:
    "Explicit roles. Accountable access. Manage your institution’s people.",
  invitations: "Invite colleagues with the permissions they need.",
  settings: "Maintain your institution’s identity and workspace information.",
  audit: "A chronological record of sensitive workspace actions.",
};
type Editor =
  | { kind: "dataset"; record?: Dataset }
  | { kind: "source"; record?: Source }
  | { kind: "invite" }
  | { kind: "role"; record: Member };
export function WorkspacePage({
  id,
  section,
}: {
  id: string;
  section: string;
}) {
  const [workspace, setWorkspace] = useState<Workspace>(),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [loading, setLoading] = useState(true),
    [version, setVersion] = useState(0),
    [offset, setOffset] = useState(0),
    [total, setTotal] = useState(0);
  const [q, setQ] = useState(""),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [classification, setClassification] = useState(""),
    [tag, setTag] = useState("");
  const [datasets, setDatasets] = useState<Dataset[]>([]),
    [sources, setSources] = useState<Source[]>([]),
    [members, setMembers] = useState<Member[]>([]),
    [invites, setInvites] = useState<Invitation[]>([]),
    [events, setEvents] = useState<Audit[]>([]),
    [settings, setSettings] = useState({ name: "", description: "" });
  const [counts, setCounts] = useState({ datasets: 0, sources: 0, members: 0 }),
    [editor, setEditor] = useState<Editor>(),
    [view, setView] = useState<Dataset>(),
    [confirm, setConfirm] = useState<{
      title: string;
      run: () => Promise<void>;
    }>(),
    [busy, setBusy] = useState(false);
  const canManage =
    workspace?.role === "owner" || workspace?.role === "administrator";
  function refresh() {
    setVersion((v) => v + 1);
  }
  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const list = await api<Workspace[]>("/institutions");
        const w = list.find((w) => w.institution.id === id);
        if (!w) throw new Error("Workspace not found");
        if (active) setWorkspace(w);
        const params = new URLSearchParams({
          offset: String(offset),
          q: search,
          status,
          classification,
          tag,
        });
        if (section === "catalog") {
          const [result, ss, mm] = await Promise.all([
            api<Page<Dataset>>(`/catalog/${id}?${params}`),
            all<Source>(`/data-sources/${id}`),
            all<Member>(`/memberships/${id}`),
          ]);
          if (active) {
            setDatasets(result.items);
            setTotal(result.total);
            setSources(ss);
            setMembers(mm);
          }
        }
        if (section === "sources") {
          const result = await api<Page<Source>>(
            `/data-sources/${id}?${params}`,
          );
          if (active) {
            setSources(result.items);
            setTotal(result.total);
          }
        }
        if (section === "members") {
          const result = await api<Page<Member>>(
            `/memberships/${id}?offset=${offset}`,
          );
          if (active) {
            setMembers(result.items);
            setTotal(result.total);
          }
        }
        if (section === "invitations") {
          const result = await api<Page<Invitation>>(
            `/invitations/${id}?offset=${offset}`,
          );
          if (active) {
            setInvites(result.items);
            setTotal(result.total);
          }
        }
        if (section === "audit") {
          const result = await api<Page<Audit>>(
            `/audit/${id}?offset=${offset}`,
          );
          if (active) {
            setEvents(result.items);
            setTotal(result.total);
          }
        }
        if (section === "settings") {
          const result = await api<{ name: string; description: string }>(
            `/institutions/${id}/settings`,
          );
          if (active) setSettings(result);
        }
        if (section === "overview") {
          const [dd, ss, mm] = await Promise.all([
            api<Page<Dataset>>(`/catalog/${id}?limit=5`),
            api<Page<Source>>(`/data-sources/${id}?limit=1`),
            api<Page<Member>>(`/memberships/${id}?limit=1`),
          ]);
          if (active) {
            setCounts({
              datasets: dd.total,
              sources: ss.total,
              members: mm.total,
            });
            setDatasets(dd.items);
          }
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [id, section, offset, search, status, classification, tag, version]);
  function removal(path: string, title: string) {
    setConfirm({
      title,
      run: async () => {
        await api(path, "DELETE");
        refresh();
      },
    });
  }
  async function saveSettings(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await api(
        `/institutions/${id}/settings`,
        "PUT",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      setMessage("Institution settings saved.");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveAccess(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = Object.fromEntries(new FormData(e.currentTarget));
      await api(
        editor?.kind === "role"
          ? `/memberships/${id}/${editor.record.id}`
          : `/invitations/${id}`,
        editor?.kind === "role" ? "PATCH" : "POST",
        body,
      );
      setEditor(undefined);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const datasetTable = (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Dataset / type</th>
            <th>Classification</th>
            <th>Status</th>
            <th>Last modified</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((d) => (
            <tr key={d.id}>
              <td>
                <strong>{d.name}</strong>
                <small>{d.file_type || d.source_category}</small>
              </td>
              <td>
                <span className="badge">{d.classification}</span>
              </td>
              <td className="mono">{d.status}</td>
              <td>{date(d.updated_at)}</td>
              <td>
                <div className="row">
                  <button className="secondary" onClick={() => setView(d)}>
                    Details
                  </button>
                  {canManage && section === "catalog" && (
                    <>
                      <button
                        className="secondary"
                        onClick={() =>
                          setEditor({ kind: "dataset", record: d })
                        }
                      >
                        Edit
                      </button>
                      <button
                        className="secondary"
                        onClick={() =>
                          removal(
                            `/catalog/${id}/${d.id}`,
                            `Delete “${d.name}” metadata?`,
                          )
                        }
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">
            {workspace?.institution.name || "Institution"} / {section}
          </span>
          <h1>{labels[section]}</h1>
          <p className="muted">{descriptions[section]}</p>
        </div>
        {canManage && section === "catalog" && (
          <button onClick={() => setEditor({ kind: "dataset" })}>
            + Register dataset
          </button>
        )}
        {canManage && section === "sources" && (
          <button onClick={() => setEditor({ kind: "source" })}>
            + Define source
          </button>
        )}
        {canManage && section === "invitations" && (
          <button onClick={() => setEditor({ kind: "invite" })}>
            + Invite member
          </button>
        )}
      </div>
      <Feedback error={error} message={message} />
      {["catalog", "sources"].includes(section) && (
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            setSearch(q);
          }}
        >
          <label>
            <span className="screen-reader">Search records</span>
            <input
              aria-label="Search records"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search records…"
            />
          </label>
          <button className="secondary">Search</button>
          {section === "catalog" && (
            <>
              <select
                aria-label="Filter status"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="">All statuses</option>
                {["draft", "registered", "archived"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
              <select
                aria-label="Filter classification"
                value={classification}
                onChange={(e) => {
                  setClassification(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="">All classifications</option>
                {["public", "internal", "confidential", "restricted"].map(
                  (s) => (
                    <option key={s}>{s}</option>
                  ),
                )}
              </select>
              <input
                aria-label="Filter tag"
                placeholder="Exact tag"
                value={tag}
                onChange={(e) => {
                  setTag(e.target.value);
                  setOffset(0);
                }}
              />
            </>
          )}
        </form>
      )}
      {loading ? (
        <div className="loading" role="status">
          Loading workspace records…
        </div>
      ) : (
        !error && (
          <>
            {section === "overview" && (
              <>
                <div className="stats">
                  <div>
                    <span className="mono">Registered datasets</span>
                    <strong>{counts.datasets}</strong>
                  </div>
                  <div>
                    <span className="mono">Source definitions</span>
                    <strong>{counts.sources}</strong>
                  </div>
                  <div>
                    <span className="mono">Workspace members</span>
                    <strong>{counts.members}</strong>
                  </div>
                </div>
                <div className="row between section">
                  <h2>Recently modified</h2>
                  <Link
                    className="text-link fine"
                    href={`/workspace/${id}/catalog`}
                  >
                    Open catalog ↗
                  </Link>
                </div>
                {datasets.length ? (
                  datasetTable
                ) : (
                  <Empty title="A clear foundation. Ready for your data.">
                    Start by registering dataset metadata and identifying its
                    owner. No files are ingested at this stage.
                  </Empty>
                )}
                <div className="card section">
                  <span className="mono">Platform scope / Step 01</span>
                  <h3>Governance before ingestion.</h3>
                  <p className="muted">
                    This workspace supports people, permissions, dataset
                    metadata, and source definitions. Connections, file
                    ingestion, and analysis will be introduced in later stages.
                  </p>
                </div>
              </>
            )}
            {section === "catalog" &&
              (datasets.length ? (
                datasetTable
              ) : (
                <Empty title="No datasets found.">
                  Register your first dataset, or adjust the search and filters.
                </Empty>
              ))}
            {section === "sources" &&
              (sources.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Category</th>
                        <th>Connection</th>
                        <th>Reference</th>
                        {canManage && <th>Actions</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {sources.map((s) => (
                        <tr key={s.id}>
                          <td>
                            <strong>{s.name}</strong>
                            <small>{s.description}</small>
                          </td>
                          <td>{s.category}</td>
                          <td>
                            <span className="badge">Not configured</span>
                          </td>
                          <td className="break">{s.reference || "—"}</td>
                          {canManage && (
                            <td>
                              <div className="row">
                                <button
                                  className="secondary"
                                  onClick={() =>
                                    setEditor({ kind: "source", record: s })
                                  }
                                >
                                  Edit
                                </button>
                                <button
                                  className="secondary"
                                  onClick={() =>
                                    removal(
                                      `/data-sources/${id}/${s.id}`,
                                      `Delete “${s.name}” source?`,
                                    )
                                  }
                                >
                                  Delete
                                </button>
                              </div>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title="No source definitions yet.">
                  Document a future data source. Defining a source does not
                  connect or import it.
                </Empty>
              ))}
            {section === "members" && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Member</th>
                      <th>Role</th>
                      <th>Account</th>
                      {canManage && <th>Actions</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((m) => (
                      <tr key={m.id}>
                        <td>
                          <strong>{m.name}</strong>
                          <small>{m.email}</small>
                        </td>
                        <td>
                          <span className="badge">{m.role}</span>
                        </td>
                        <td>{m.status}</td>
                        {canManage && (
                          <td>
                            <div className="row">
                              <button
                                className="secondary"
                                onClick={() =>
                                  setEditor({ kind: "role", record: m })
                                }
                              >
                                Change role
                              </button>
                              <button
                                className="secondary"
                                onClick={() =>
                                  removal(
                                    `/memberships/${id}/${m.id}`,
                                    `Remove ${m.name} from this institution?`,
                                  )
                                }
                              >
                                Remove
                              </button>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {section === "invitations" &&
              (invites.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th>Role</th>
                        <th>State</th>
                        <th>Expires</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {invites.map((i) => (
                        <tr key={i.id}>
                          <td>{i.email}</td>
                          <td>{i.role}</td>
                          <td>
                            {i.accepted_at
                              ? "Accepted"
                              : i.revoked_at
                                ? "Revoked"
                                : new Date(i.expires_at) < new Date()
                                  ? "Expired"
                                  : "Pending"}
                          </td>
                          <td>{date(i.expires_at)}</td>
                          <td>
                            {!i.accepted_at && !i.revoked_at && (
                              <button
                                className="secondary"
                                onClick={() =>
                                  removal(
                                    `/invitations/${id}/${i.id}`,
                                    "Revoke this invitation?",
                                  )
                                }
                              >
                                Revoke
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title="No invitations yet.">
                  Invite colleagues by email. Links expire after seven days and
                  can be used once.
                </Empty>
              ))}
            {section === "settings" && (
              <form
                className="card stack"
                style={{ maxWidth: 700 }}
                onSubmit={saveSettings}
              >
                <label>
                  Institution name
                  <input
                    name="name"
                    required
                    maxLength={160}
                    defaultValue={settings.name}
                    disabled={!canManage}
                  />
                </label>
                <label>
                  Description
                  <textarea
                    name="description"
                    maxLength={5000}
                    defaultValue={settings.description}
                    disabled={!canManage}
                  />
                </label>
                {canManage && (
                  <button disabled={busy}>
                    {busy ? "Saving…" : "Save settings"}
                  </button>
                )}
              </form>
            )}
            {section === "audit" &&
              (events.length ? (
                <AuditTable events={events} />
              ) : (
                <Empty title="No activity recorded.">
                  Sensitive workspace actions will appear here as they occur.
                </Empty>
              ))}
            {["catalog", "sources", "members", "invitations", "audit"].includes(
              section,
            ) && (
              <Pagination total={total} offset={offset} setOffset={setOffset} />
            )}
          </>
        )
      )}
      {editor && (
        <Modal
          title={
            editor.kind === "dataset"
              ? "Dataset metadata"
              : editor.kind === "source"
                ? "Source definition"
                : editor.kind === "invite"
                  ? "Invite a colleague"
                  : "Change member role"
          }
          onClose={() => setEditor(undefined)}
        >
          {editor.kind === "dataset" ? (
            <CatalogForm
              id={id}
              record={editor.record}
              sources={sources}
              members={members}
              onSaved={() => {
                setEditor(undefined);
                refresh();
              }}
            />
          ) : editor.kind === "source" ? (
            <SourceForm
              id={id}
              record={editor.record}
              onSaved={() => {
                setEditor(undefined);
                refresh();
              }}
            />
          ) : (
            <form className="stack" onSubmit={saveAccess}>
              <Feedback error={error} />
              {editor.kind === "invite" && (
                <label>
                  Email address
                  <input name="email" type="email" required />
                </label>
              )}
              <label>
                Role
                <select
                  name="role"
                  defaultValue={
                    editor.kind === "role" ? editor.record.role : "viewer"
                  }
                >
                  {(workspace?.role === "owner"
                    ? ["owner", "administrator", "analyst", "viewer"]
                    : ["analyst", "viewer"]
                  ).map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </label>
              <p className="muted fine">
                Owners control permissions. Administrators manage members and
                catalog records. Analysts and viewers can read workspace
                resources in Step 01.
              </p>
              <button disabled={busy}>
                {busy
                  ? "Saving…"
                  : editor.kind === "invite"
                    ? "Send invitation"
                    : "Save role"}
              </button>
            </form>
          )}
        </Modal>
      )}
      {view && (
        <Modal title={view.name} onClose={() => setView(undefined)}>
          <p>{view.description || "No description supplied."}</p>
          <dl className="stack">
            {Object.entries({
              Classification: view.classification,
              Status: view.status,
              "Source category": view.source_category,
              "File type": view.file_type || "—",
              Tags: view.tags?.join(", ") || "—",
              "Record count": view.record_count ?? "Not supplied",
              "Storage bytes": view.storage_bytes ?? "Not supplied",
              "Source reference": view.source_reference || "—",
              "Owner ID": view.owner_id,
              "Source ID": view.source_id || "Not associated",
              Created: date(view.created_at),
              Modified: date(view.updated_at),
            }).map(([k, v]) => (
              <div key={k}>
                <dt className="mono">{k}</dt>
                <dd className="break" style={{ margin: "5px 0" }}>
                  {v}
                </dd>
              </div>
            ))}
          </dl>
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
export function AuditTable({ events }: { events: Audit[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Action</th>
            <th>Actor / target</th>
            <th>Request ID</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td>{date(e.created_at)}</td>
              <td>{e.action}</td>
              <td className="number break">
                {e.actor_id || "Unauthenticated"}
                <small>{e.target}</small>
              </td>
              <td className="number break">{e.request_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
