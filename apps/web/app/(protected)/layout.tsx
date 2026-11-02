import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Shell } from "@/components/shell";
import type { Me } from "@/lib/api";
export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookie = await cookies();
  const upstream =
    process.env.API_INTERNAL_URL?.trim().replace(/\/+$/, "") ||
    (process.env.NODE_ENV === "production" ? null : "http://127.0.0.1:8000");
  if (!upstream) throw new Error("The identity service is not configured.");
  let response: Response;
  try {
    response = await fetch(`${upstream}/api/v1/auth/me`, {
      headers: { Cookie: cookie.toString() },
      cache: "no-store",
    });
  } catch {
    throw new Error("The identity service is unavailable. Please retry.");
  }
  if (response.status === 401) redirect("/login");
  if (!response.ok)
    throw new Error("The identity service is unavailable. Please retry.");
  const me: Me = await response.json();
  return <Shell me={me}>{children}</Shell>;
}
