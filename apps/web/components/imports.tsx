"use client";
import { useEffect, useRef, useState, FormEvent } from "react";
import { createSHA256 } from "hash-wasm";
import { api, uploadChunk, all, Dataset, Page } from "@/lib/api";
import { Feedback } from "./ui";
type FileRecord = {
  id: string;
  name: string;
  state: string;
  received: number;
  size: number;
  error: string;
};
export function Imports({ id }: { id: string }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]),
    [records, setRecords] = useState<FileRecord[]>([]),
    [selected, setSelected] = useState<File>(),
    [progress, setProgress] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [results, setResults] = useState<
      { file_id: string; name: string; reference: string; snippet: string }[]
    >([]);
  const stop = useRef(false);
  async function refresh() {
    const result = await api<Page<FileRecord>>(`/ingestion/${id}/files`);
    setRecords(result.items);
  }
  useEffect(() => {
    all<Dataset>(`/catalog/${id}`)
      .then(setDatasets)
      .catch((e) => setError(e.message));
    void refresh();
    const timer = setInterval(() => {
      refresh().catch((e) => setError(e.message));
    }, 5000);
    return () => clearInterval(timer);
  }, [id]);
  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selected) return;
    const dataset_id = new FormData(e.currentTarget).get("dataset_id");
    stop.current = false;
    setBusy(true);
    setError("");
    try {
      const hash = await createSHA256();
      hash.init();
      for (let offset = 0; offset < selected.size; offset += 4 * 1024 * 1024) {
        if (stop.current) return;
        hash.update(
          new Uint8Array(
            await selected
              .slice(offset, offset + 4 * 1024 * 1024)
              .arrayBuffer(),
          ),
        );
        setProgress(
          `Checking integrity: ${Math.round((offset / selected.size) * 100)}%`,
        );
      }
      const record = await api<FileRecord>(`/ingestion/${id}/files`, "POST", {
        dataset_id,
        name: selected.name,
        size: selected.size,
        checksum: hash.digest(),
      });
      for (
        let offset = record.received;
        offset < selected.size;
        offset += 4 * 1024 * 1024
      ) {
        if (stop.current) return;
        await uploadChunk(
          `/ingestion/${id}/files/${record.id}/chunks?offset=${offset}`,
          selected.slice(offset, offset + 4 * 1024 * 1024),
        );
        setProgress(
          `Uploading: ${Math.min(100, Math.round(((offset + 4 * 1024 * 1024) / selected.size) * 100))}%`,
        );
      }
      await api(`/ingestion/${id}/files/${record.id}/complete`, "POST");
      setProgress("Queued for processing.");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h1>Imports & search</h1>
      <p>
        Upload TXT, CSV, JSON or JSONL files. Select the same file to resume an
        interrupted upload. Extraction currently supports UTF-8 text up to 64
        MiB.
      </p>
      <Feedback error={error} message={progress} />
      <form
        onSubmit={upload}
        className="card stack"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          setSelected(e.dataTransfer.files[0]);
        }}
      >
        <label>
          Dataset
          <select name="dataset_id" required>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Choose or drop a file
          <input
            type="file"
            accept=".txt,.csv,.json,.jsonl"
            onChange={(e) => setSelected(e.target.files?.[0])}
          />
        </label>
        <p>{selected?.name}</p>
        <div className="row">
          <button disabled={busy || !selected}>Upload / resume</button>
          {busy && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                stop.current = true;
              }}
            >
              Pause
            </button>
          )}
        </div>
      </form>
      <h2 className="section">Import history</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Status</th>
              <th>Bytes received</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.id}>
                <td>
                  {r.name}
                  <small>{r.error}</small>
                </td>
                <td>{r.state}</td>
                <td>
                  {r.received} / {r.size}
                </td>
                <td>
                  <div className="row">
                    {["ready", "failed"].includes(r.state) && (
                      <button
                        onClick={() =>
                          api(
                            `/ingestion/${id}/files/${r.id}/reprocess`,
                            "POST",
                          )
                            .then(refresh)
                            .catch((e) => setError(e.message))
                        }
                      >
                        Reprocess
                      </button>
                    )}
                    {r.state !== "cancelled" && (
                      <button
                        className="secondary"
                        onClick={() => {
                          if (
                            window.confirm(
                              "Cancel and remove this file and extracted content?",
                            )
                          )
                            api(`/ingestion/${id}/files/${r.id}`, "DELETE")
                              .then(refresh)
                              .catch((e) => setError(e.message));
                        }}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2 className="section">Search extracted content</h2>
      <form
        className="row"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const q = new FormData(e.currentTarget).get("q");
            setResults(
              await api(
                `/ingestion/${id}/search?q=${encodeURIComponent(String(q))}`,
              ),
            );
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      >
        <input
          name="q"
          aria-label="Search extracted content"
          required
          maxLength={200}
        />
        <button>Search</button>
      </form>
      {results.map((r, i) => (
        <article className="card section" key={i}>
          <strong>{r.name}</strong>
          <p>{r.snippet}</p>
          <span className="mono">{r.reference}</span>
          <p>
            <a
              className="text-link"
              href={`/api/v1/ingestion/${id}/files/${r.file_id}/download`}
            >
              Download original
            </a>
          </p>
        </article>
      ))}
    </>
  );
}
