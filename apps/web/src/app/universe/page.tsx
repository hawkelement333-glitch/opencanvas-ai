import { DynamicUniverseApp } from "@/components/universe/dynamic-universe-app";

function value(item: string | string[] | undefined): string | undefined {
  return typeof item === "string" ? item : undefined;
}

export default async function UniversePage({
  searchParams,
}: {
  searchParams: Promise<{
    workspaceId?: string | string[];
    canvasId?: string | string[];
    workflowExecutionId?: string | string[];
    retrievalId?: string | string[];
    bundleId?: string | string[];
  }>;
}) {
  const params = await searchParams;
  return (
    <DynamicUniverseApp
      requestedWorkspaceId={value(params.workspaceId)}
      requestedCanvasId={value(params.canvasId)}
      requestedWorkflowExecutionId={value(params.workflowExecutionId)}
      requestedRetrievalId={value(params.retrievalId)}
      requestedBundleId={value(params.bundleId)}
    />
  );
}
