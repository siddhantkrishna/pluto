"use client";
import { FormEvent, useState } from "react";
import { api, Dataset, Source, Member } from "@/lib/api";
import { Feedback } from "./ui";
export const categories = [
  "local_file",
  "google_drive",
  "database",
  "api",
  "file_storage",
];
export function CatalogForm({
  id,
  record,
  sources,
  members,
  onSaved,
}: {
  id: string;
  record?: Dataset;
  sources: Source[];
  members: Member[];
  onSaved: () => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = Object.fromEntries(new FormData(e.currentTarget));
    try {
      await api(
        `/catalog/${id}${record ? "/" + record.id : ""}`,
        record ? "PUT" : "POST",
        {
          ...d,
          record_count: d.record_count === "" ? null : Number(d.record_count),
          storage_bytes:
            d.storage_bytes === "" ? null : Number(d.storage_bytes),
          source_id: d.source_id || null,
          tags: String(d.tags)
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
        },
      );
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="stack">
      <Feedback error={error} />
      <div className="form-grid">
        <label className="wide">
          Dataset name
          <input
            name="name"
            required
            maxLength={160}
            defaultValue={record?.name}
          />
        </label>
        <label className="wide">
          Description
          <textarea
            name="description"
            maxLength={5000}
            defaultValue={record?.description}
          />
        </label>
        <label>
          Source category
          <select
            name="source_category"
            defaultValue={record?.source_category || "local_file"}
          >
            {categories.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          File / source type
          <input
            name="file_type"
            maxLength={80}
            defaultValue={record?.file_type}
            placeholder="e.g. CSV, PostgreSQL"
          />
        </label>
        <label>
          Classification
          <select
            name="classification"
            defaultValue={record?.classification || "internal"}
          >
            {["public", "internal", "confidential", "restricted"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select name="status" defaultValue={record?.status || "draft"}>
            {["draft", "registered", "archived"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Authorized owner
          <select name="owner_id" required defaultValue={record?.owner_id}>
            {members
              .filter((m) => m.status === "active")
              .map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Associated source
          <select name="source_id" defaultValue={record?.source_id || ""}>
            <option value="">No association</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Record count
          <input
            name="record_count"
            type="number"
            min="0"
            step="1"
            defaultValue={record?.record_count ?? ""}
          />
        </label>
        <label>
          Storage size (bytes)
          <input
            name="storage_bytes"
            type="number"
            min="0"
            step="1"
            defaultValue={record?.storage_bytes ?? ""}
          />
        </label>
        <label className="wide">
          Tags, separated by commas
          <input name="tags" defaultValue={record?.tags?.join(", ")} />
        </label>
        <label className="wide">
          Source reference (no credentials or query parameters)
          <input
            name="source_reference"
            maxLength={500}
            defaultValue={record?.source_reference}
          />
        </label>
      </div>
      <p className="muted fine">
        This registers metadata only. Files are not uploaded or processed.
      </p>
      <button disabled={busy}>
        {busy ? "Saving…" : "Save dataset metadata"}
      </button>
    </form>
  );
}
export function SourceForm({
  id,
  record,
  onSaved,
}: {
  id: string;
  record?: Source;
  onSaved: () => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        `/data-sources/${id}${record ? "/" + record.id : ""}`,
        record ? "PUT" : "POST",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="stack">
      <Feedback error={error} />
      <label>
        Source name
        <input
          name="name"
          required
          maxLength={160}
          defaultValue={record?.name}
        />
      </label>
      <label>
        Category
        <select name="category" defaultValue={record?.category || "local_file"}>
          {categories.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </label>
      <label>
        Description
        <textarea
          name="description"
          maxLength={5000}
          defaultValue={record?.description}
        />
      </label>
      <label>
        Reference (no credentials or query parameters)
        <input
          name="reference"
          maxLength={500}
          defaultValue={record?.reference}
        />
      </label>
      <p className="muted fine">
        Definition only. Connectors and credential storage are not available in
        Step 01. Do not enter secrets in metadata fields.
      </p>
      <button disabled={busy}>
        {busy ? "Saving…" : "Save source definition"}
      </button>
    </form>
  );
}
