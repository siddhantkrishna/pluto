import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Shell } from "@/components/shell";
import { HttpError } from "@/lib/server/db";
import { currentIdentity } from "@/lib/server/auth";

export const runtime = "nodejs";
export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const token = (await cookies()).get("pluto_session")?.value;
  if (!token) redirect("/login");
  let identity;
  try {
    identity = await currentIdentity();
  } catch (error) {
    if (error instanceof HttpError && error.status === 401) redirect("/login");
    throw error;
  }
  return (
    <Shell me={{ user: identity.user, csrf: identity.csrf,
      platform_admin: identity.platform_admin }}>
      {children}
    </Shell>
  );
}
