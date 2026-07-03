# Session Tracker

One entry point to every project I work on — an agentic session-management app.
It turns my real way-of-working (`.ai/` workspace, `_tracker.md` index, plan-before-code)
into a full-stack app with a LangGraph agent and an MCP server.

Build progress lives in [`_tracker.md`](./_tracker.md).

## Stack
- **Backend:** FastAPI (Python, uv)
- **Frontend:** Next.js → Cloudflare Pages
- **DB:** Postgres + pgvector
- **Agent:** LangGraph · MCP server
- **Observability:** Langfuse

## Local dev
1. Start the database: `docker compose up -d`
2. Backend: `cd backend && uv run uvicorn app.main:app --reload` → http://localhost:8000/health
3. Frontend: `cd frontend && npm run dev` → http://localhost:3000
