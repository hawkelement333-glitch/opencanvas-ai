from fastapi import APIRouter

from opencanvas_api.api.routes import (
    agents,
    auth,
    canonical,
    canvases,
    documents,
    domain_events,
    graph_retrieval,
    health,
    knowledge_graph,
    traces,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["authentication"])
api_router.include_router(canvases.router, tags=["canvases"])
api_router.include_router(documents.router, tags=["documents"])
api_router.include_router(traces.router, tags=["traces"])
api_router.include_router(canonical.router, tags=["canonical"])
api_router.include_router(knowledge_graph.router, tags=["knowledge-graph"])
api_router.include_router(domain_events.router, tags=["living-state-events"])
api_router.include_router(graph_retrieval.router, tags=["graph-aware-retrieval"])
api_router.include_router(agents.router, tags=["controlled-agent-inspection"])
api_router.include_router(workflows.router, tags=["controlled-ai-workflows"])
