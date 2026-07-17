# OpenCanvas AI MVP checklist

- [x] Inspect the existing scaffold, architecture, and implementation plan.
- [x] Narrow the data model to canvas, text/AI nodes, directional edges, AI requests, and AI responses.
- [x] Add the PostgreSQL schema and Alembic migration.
- [x] Add validated canvas, node, edge, snapshot, and AI APIs.
- [x] Build the React Flow canvas with create/open, edit, move, resize, duplicate, delete, connect, and multi-select.
- [x] Add debounced autosave, explicit save, conflict/error feedback, and refresh restoration.
- [x] Add server-only OpenAI Responses API integration plus no-key mock mode.
- [x] Insert every completed AI answer as a connected, editable canvas node.
- [x] Add unit, integration, and end-to-end coverage for the complete workflow.
- [x] Run installation, migration, format, lint, type check, tests, end-to-end tests, and production build.
- [x] Manually verify the create → connect → refresh → multi-select → ask → answer-node journey.

Out of scope for this milestone: authentication, uploads, PDFs, document ingestion, image generation, real-time collaboration, and agent systems.
