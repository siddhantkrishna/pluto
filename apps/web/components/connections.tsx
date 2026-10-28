"use client";
import { useEffect, useState, FormEvent } from "react";
import Script from "next/script";
import { api, Dataset } from "@/lib/api";
import { Feedback } from "./ui";
declare global {
  interface Window {
    plutoPick?: (config: Record<string, string>) => Promise<string[]>;
  }
}
type Connection = { id: string; provider: string; state: string };
export function Connections({
  id,
  datasets,
}: {
  id: string;
  datasets: Dataset[];
}) {
  const [connections, setConnections] = useState<Connection[]>([]),
    [dataset, setDataset] = useState(""),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [tables, setTables] = useState<{ schema: string; table: string }[]>([]),
    [database, setDatabase] = useState("");
  async function load() {
    setConnections(await api(`/connectors/${id}`));
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [id]);
  async function action(run: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await run();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function postgres(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    await action(async () => {
      const result = await api<{
        id: string;
        tables: { schema: string; table: string }[];
      }>(`/connectors/${id}/postgres`, "POST", {
        ...data,
        port: Number(data.port),
      });
      setTables(result.tables);
      setDatabase(result.id);
      form.reset();
      setMessage("Database validated. Select an authorized table below.");
    });
  }
  return (
    <section className="card stack section">
      <Script src="/pluto-picker.js" />
      <h2>Authorized sources</h2>
      <Feedback error={error} message={message} />
      <label>
        Destination dataset
        <select value={dataset} onChange={(e) => setDataset(e.target.value)}>
          <option value="">Select dataset</option>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <button
        disabled={busy}
        onClick={() =>
          action(async () => {
            const result = await api<{ url: string }>(
              `/connectors/${id}/google/authorize`,
              "POST",
            );
            window.location.assign(result.url);
          })
        }
      >
        Connect Google Drive
      </button>
      {connections
        .filter((c) => c.state === "active")
        .map((c) => (
          <div key={c.id} className="row">
            <span>
              {c.provider} / {c.id.slice(0, 8)}
            </span>
            {c.provider === "google" ? (
              <>
                <button
                  disabled={busy || !dataset}
                  onClick={() =>
                    action(async () => {
                      const config = await api<Record<string, string>>(
                        `/connectors/${id}/${c.id}/picker`,
                        "POST",
                      );
                      if (!window.plutoPick)
                        throw new Error("Picker is still loading");
                      const files = await window.plutoPick(config);
                      if (files.length) {
                        await api(`/connectors/${id}/${c.id}/import`, "POST", {
                          dataset_id: dataset,
                          file_ids: files,
                        });
                        setMessage("Selected files registered for processing.");
                      }
                    })
                  }
                >
                  Select files in Google Picker
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      const result = await api<{ has_more: boolean }>(
                        `/connectors/${id}/${c.id}/sync`,
                        "POST",
                      );
                      setMessage(
                        result.has_more
                          ? "Sync page processed. Run sync again for remaining changes."
                          : "Authorized changes synchronized.",
                      );
                    })
                  }
                >
                  Synchronize
                </button>
              </>
            ) : (
              <button
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    setDatabase(c.id);
                    setTables(await api(`/connectors/${id}/${c.id}/tables`));
                  })
                }
              >
                Browse tables
              </button>
            )}
            {c.provider === "postgres" && (
              <button
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    const result = await api<{ updated: number }>(
                      `/connectors/${id}/${c.id}/sync`,
                      "POST",
                    );
                    setMessage(
                      `${result.updated} incremental imports queued. Append-only cursors must be configured.`,
                    );
                  })
                }
              >
                Import new rows
              </button>
            )}
            <button
              className="secondary"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    "Disconnect and remove access to imported content?",
                  )
                )
                  void action(async () => {
                    await api(`/connectors/${id}/${c.id}`, "DELETE");
                  });
              }}
            >
              Disconnect
            </button>
          </div>
        ))}
      <details>
        <summary>Connect read-only PostgreSQL</summary>
        <form className="stack section" onSubmit={postgres}>
          {["host", "database", "username", "password", "port"].map((key) => (
            <label key={key}>
              {key}
              <input
                name={key}
                type={
                  key === "password"
                    ? "password"
                    : key === "port"
                      ? "number"
                      : "text"
                }
                required
                defaultValue={key === "port" ? "5432" : undefined}
                autoComplete="off"
              />
            </label>
          ))}
          <p>
            Only operator-allowlisted public hosts with verified TLS are
            permitted.
          </p>
          <button disabled={busy}>Validate and connect</button>
        </form>
      </details>
      {tables.length > 0 && (
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            const value = String(new FormData(e.currentTarget).get("table"));
            const table = tables[Number(value)];
            const cursor_column = String(
              new FormData(e.currentTarget).get("cursor_column") || "",
            );
            void action(async () => {
              await api(`/connectors/${id}/${database}/table-import`, "POST", {
                dataset_id: dataset,
                schema_name: table.schema,
                table: table.table,
                cursor_column,
              });
              setMessage("Read-only snapshot import queued.");
            });
          }}
        >
          <input
            name="cursor_column"
            aria-label="Append-only primary-key cursor"
            placeholder="Optional append-only primary key"
          />
          <select name="table" aria-label="Authorized table">
            {tables.map((t, i) => (
              <option key={i} value={i}>
                {t.schema}.{t.table}
              </option>
            ))}
          </select>
          <button disabled={busy || !dataset}>Import table snapshot</button>
        </form>
      )}
    </section>
  );
}
