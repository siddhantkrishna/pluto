"use client";
import { useEffect, useRef, useState } from "react";
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="dialog"
      onCancel={onClose}
      aria-labelledby="dialog-title"
    >
      <div className="row between">
        <h2 id="dialog-title">{title}</h2>
        <button
          className="secondary"
          onClick={onClose}
          aria-label="Close dialog"
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="mono">PLUTO / REGISTRY</span>
      <h2 className="section">{title}</h2>
      <p>{children}</p>
    </div>
  );
}
export function Feedback({
  error,
  message,
}: {
  error?: string;
  message?: string;
}) {
  return (
    <>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="notice" role="status">
          {message}
        </div>
      )}
    </>
  );
}
export function Pagination({
  total,
  offset,
  setOffset,
}: {
  total: number;
  offset: number;
  setOffset: (n: number) => void;
}) {
  return (
    <div className="pagination">
      <span className="mono">
        {total === 0 ? "0" : offset + 1}–{Math.min(offset + 50, total)} /{" "}
        {total} records
      </span>
      <div className="row">
        <button
          className="secondary"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Previous
        </button>
        <button
          className="secondary"
          disabled={offset + 50 >= total}
          onClick={() => setOffset(offset + 50)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
export function Confirm({
  title,
  onConfirm,
  onClose,
}: {
  title: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <p>This change takes effect immediately. Confirm to continue.</p>
      <Feedback error={error} />
      <div className="row section">
        <button
          className="danger"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
              onClose();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Confirm
        </button>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}
export const date = (value: string) => new Date(value).toLocaleString();
