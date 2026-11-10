# part of server.py (WFL-14, docs/N8N-MIGRATION.md §4.1): the runner's view of n8n's workflows for the app's pages. n8n's
# editor itself is served under /n8n/ like the stack's other tools (server.frames.py).
# GET /api/workflows is the runner's view of every workflow and its recent runs (ops/flows_view.py) for the app's pages.


async def api_workflows(request):
    """WFL-14: every workflow in git with its schedule, its steps and its recent runs (public/workflows-runs.json)."""
    try:
        return JSONResponse(json.loads((M / "public/workflows-runs.json").read_text()))
    except (OSError, ValueError):
        return JSONResponse({"workflows": [], "generated": None})
