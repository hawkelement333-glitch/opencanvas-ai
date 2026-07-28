from fastapi import APIRouter

from opencanvas_api.api.routes import (
    agent_studio,
    agents,
    auth,
    canonical,
    canvases,
    collaboration,
    documents,
    domain_events,
    graph_retrieval,
    health,
    indexing,
    knowledge_graph,
    traces,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["authentication"])
api_router.include_router(canvases.router, tags=["canvases"])
api_router.include_router(collaboration.router, tags=["workspace-collaboration"])
api_router.include_router(documents.router, tags=["documents"])
api_router.include_router(indexing.router, tags=["deterministic-indexing"])
api_router.include_router(traces.router, tags=["traces"])
api_router.include_router(canonical.router, tags=["canonical"])
api_router.include_router(knowledge_graph.router, tags=["knowledge-graph"])
api_router.include_router(domain_events.router, tags=["living-state-events"])
api_router.include_router(graph_retrieval.router, tags=["graph-aware-retrieval"])
api_router.include_router(agents.router, tags=["controlled-agent-inspection"])
api_router.include_router(workflows.router, tags=["controlled-ai-workflows"])
api_router.include_router(agent_studio.router, tags=["bounded-agent-studio"])
