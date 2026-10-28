import Link from "next/link";
export default function NotFound() {
  return (
    <main className="workspace-list">
      <span className="mono">404 / Not found</span>
      <h1>This page is unavailable.</h1>
      <Link href="/workspaces" className="button">
        Return to workspaces
      </Link>
    </main>
  );
}
