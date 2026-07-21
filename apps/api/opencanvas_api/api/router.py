from fastapi import APIRouter

from opencanvas_api.api.routes import agents, auth, canonical, canvases, documents, health, traces

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["authentication"])
api_router.include_router(canvases.router, tags=["canvases"])
api_router.include_router(documents.router, tags=["documents"])
api_router.include_router(traces.router, tags=["traces"])
api_router.include_router(canonical.router, tags=["canonical"])
api_router.include_router(agents.router, tags=["controlled-agent-inspection"])
