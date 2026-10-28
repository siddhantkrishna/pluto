"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="workspace-list">
      <h1>Unable to load this page.</h1>
      <p>The service may be unavailable. Please retry.</p>
      <button onClick={reset}>Retry</button>
    </main>
  );
}
