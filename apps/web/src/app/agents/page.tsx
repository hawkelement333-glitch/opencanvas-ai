import { AgentStudioApp } from "@/components/agent-studio/agent-studio-app";

function value(item: string | string[] | undefined): string | undefined {
  return typeof item === "string" ? item : undefined;
}

export default async function AgentsPage({
  searchParams,
}: {
  searchParams: Promise<{
    workspaceId?: string | string[];
    canvasId?: string | string[];
    agentId?: string | string[];
  }>;
}) {
  const params = await searchParams;
  return (
    <AgentStudioApp
      requestedWorkspaceId={value(params.workspaceId)}
      requestedCanvasId={value(params.canvasId)}
      requestedAgentId={value(params.agentId)}
    />
  );
}
