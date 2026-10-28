import Link from "next/link";
export default function Home() {
  return (
    <>
      <header className="public-header">
        <span className="brand">
          PLUTO<small>BY VOGON</small>
        </span>
        <Link className="button secondary" href="/login">
          Sign in ↗
        </Link>
      </header>
      <main className="landing">
        <span className="eyebrow">VOGON / Enterprise data infrastructure</span>
        <h1>
          A foundation for
          <br />
          institutional intelligence.
        </h1>
        <p>
          Bring order to your organization’s data. A dedicated workspace for
          your people, sources, and institutional knowledge.
        </p>
        <div className="row section">
          <Link href="/register" className="button">
            Create an account ↗
          </Link>
          <Link href="/login" className="button secondary">
            Open your workspace
          </Link>
        </div>
        <div className="rule" />
        <div className="grid">
          <section>
            <span className="mono">01 / GOVERNANCE</span>
            <h3>Institutional boundaries.</h3>
            <p className="muted">
              Separate workspaces, explicit roles, and accountable
              administration.
            </p>
          </section>
          <section>
            <span className="mono">02 / CATALOG</span>
            <h3>Know what you hold.</h3>
            <p className="muted">
              Register dataset metadata, classify records, and identify
              responsible owners.
            </p>
          </section>
          <section>
            <span className="mono">03 / FOUNDATION</span>
            <h3>Built to grow deliberately.</h3>
            <p className="muted">
              The core platform is the first step. Data ingestion and analytical
              capabilities follow separately.
            </p>
          </section>
        </div>
      </main>
    </>
  );
}
