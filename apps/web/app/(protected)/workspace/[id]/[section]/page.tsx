import { notFound } from "next/navigation";
import { WorkspacePage } from "@/components/workspace-page";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string; section: string }>;
}) {
  const { id, section } = await params;
  if (
    ![
      "overview",
      "catalog",
      "sources",
      "members",
      "invitations",
      "settings",
      "audit",
    ].includes(section)
  )
    notFound();
  return <WorkspacePage key={`${id}/${section}`} id={id} section={section} />;
}
