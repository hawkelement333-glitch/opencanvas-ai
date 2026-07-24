import { OpenCanvasApp } from "@/components/open-canvas-app";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ rollbackEffectId?: string | string[] }>;
}) {
  const effect = (await searchParams).rollbackEffectId;
  return <OpenCanvasApp rollbackEffectId={typeof effect === "string" ? effect : undefined} />;
}
