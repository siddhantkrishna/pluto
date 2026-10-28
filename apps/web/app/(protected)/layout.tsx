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
  const response = await fetch(
    `${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/auth/me`,
    { headers: { Cookie: cookie.toString() }, cache: "no-store" },
  );
  if (response.status === 401) redirect("/login");
  if (!response.ok)
    throw new Error("The identity service is unavailable. Please retry.");
  const me: Me = await response.json();
  return <Shell me={me}>{children}</Shell>;
}
