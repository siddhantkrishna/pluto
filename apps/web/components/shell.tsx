"use client";
import Link from "next/link";
import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, Me, Workspace, setCSRF } from "@/lib/api";
import { Feedback } from "./ui";
const Identity = createContext<Me | null>(null);
export function useIdentity() {
  return useContext(Identity)!;
}
export function Shell({ me, children }: { me: Me; children: React.ReactNode }) {
  const path = usePathname(),
    router = useRouter();
  const [collapsed, setCollapsed] = useState(false),
    [workspaces, setWorkspaces] = useState<Workspace[]>([]),
    [error, setError] = useState("");
  const id = path.match(/^\/workspace\/([^/]+)/)?.[1];
  const workspace = workspaces.find((w) => w.institution.id === id);
  useEffect(() => {
    setCSRF(me.csrf);
  }, [me.csrf]);
  useEffect(() => {
    api<Workspace[]>("/institutions")
      .then(setWorkspaces)
      .catch((e) => setError(e.message));
  }, [path]);
  const role = workspace?.role;
  const admin = role === "owner" || role === "administrator";
  const links = id
    ? [
        ["overview", "Overview"],
        ["catalog", "Data catalog"],
        ["imports", "Imports & search"],
        ["sources", "Data sources"],
        ["members", "Members"],
        ...(admin
          ? [
              ["invitations", "Invitations"],
              ["settings", "Settings"],
              ["audit", "Activity"],
            ]
          : []),
      ]
    : [];
  return (
    <Identity.Provider value={me}>
      <a className="skip" href="#main-content">
        Skip to content
      </a>
      <div className={`shell ${collapsed ? "collapsed" : ""}`}>
        <aside className="sidebar">
          <Link href="/workspaces" className="brand">
            PLUTO<small>VOGON</small>
          </Link>
          <button
            className="secondary"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
          >
            ☰
          </button>
          <label className="workspace-switch">
            <span className="mono">Institution</span>
            <select
              aria-label="Switch institution"
              value={id || ""}
              onChange={(e) =>
                router.push(
                  e.target.value
                    ? `/workspace/${e.target.value}/overview`
                    : "/workspaces",
                )
              }
            >
              <option value="">All workspaces</option>
              {workspaces.map((w) => (
                <option key={w.institution.id} value={w.institution.id}>
                  {w.institution.name}
                </option>
              ))}
            </select>
          </label>
          <nav aria-label="Main navigation">
            <Link
              href="/workspaces"
              className={path === "/workspaces" ? "active" : ""}
              title="Workspaces"
            >
              <span className="nav-icon" aria-hidden="true">
                00
              </span>
              <span className="nav-label">Workspaces</span>
            </Link>
            {links.map(([slug, label], i) => (
              <Link
                title={label}
                aria-label={label}
                key={slug}
                href={`/workspace/${id}/${slug}`}
                className={path.endsWith("/" + slug) ? "active" : ""}
              >
                <span className="nav-icon" aria-hidden="true">
                  0{i + 1}
                </span>
                <span className="nav-label">{label}</span>
              </Link>
            ))}
            <Link
              title="Account"
              href="/account"
              className={path === "/account" ? "active" : ""}
            >
              <span className="nav-icon" aria-hidden="true">
                ↗
              </span>
              <span className="nav-label">Account & security</span>
            </Link>
            {me.platform_admin && (
              <Link
                title="Platform"
                href="/platform"
                className={path === "/platform" ? "active" : ""}
              >
                <span className="nav-icon" aria-hidden="true">
                  P
                </span>
                <span className="nav-label">Platform administration</span>
              </Link>
            )}
          </nav>
          <div className="foot">
            <p className="mono">
              Core platform
              <br />
              PLUTO / VOGON
            </p>
          </div>
        </aside>
        <div>
          <header className="topbar">
            <span className="mono">
              PLUTO / {workspace?.institution.name || "Account"} /{" "}
              {path.split("/").at(-1)?.replaceAll("-", " ")}
            </span>
            <span className="row">
              <span>{me.user.name}</span>
              {role && <span className="badge">{role}</span>}
              <button
                className="secondary"
                onClick={async () => {
                  try {
                    await api("/auth/logout", "POST");
                    window.location.href = "/login";
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                Sign out
              </button>
            </span>
          </header>
          <main id="main-content" className="content">
            <Feedback error={error} />
            {children}
          </main>
        </div>
      </div>
    </Identity.Provider>
  );
}
