import { CollaborationApp } from "@/components/collaboration/collaboration-app";

export default async function CollaborationPage({
  searchParams,
}: {
  searchParams: Promise<{ workspaceId?: string | string[] }>;
}) {
  const value = (await searchParams).workspaceId;
  return <CollaborationApp initialWorkspaceId={typeof value === "string" ? value : undefined} />;
}
