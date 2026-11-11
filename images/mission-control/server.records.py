# part of server.py (REC-06, ops/domain/records.py): the deployment's records, links and measures for the Measures view.
# The tracker poller writes them beside the runner's state (public/records.json) after each pass of its read cache; here
# they are served to a signed-in session (the gate before it has checked the sign-in), never to the AI phone, never
# cached, and never part of the state every screen gets.
RECORDS_VIEW = M / "public/records.json"


async def api_records(request):
    """REC-06: each tracker that names its pack's records: types, links, gates, records, the queries and the measures."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not on the AI phone: the records show on your own devices"}, status_code=403)
    try:
        d = json.loads(await asyncio.to_thread(RECORDS_VIEW.read_text))
    except FileNotFoundError:
        d = {"trackers": [], "made": None}
    except (OSError, ValueError):                       # cut short or unreadable: said, never shown half
        d = {"trackers": [], "made": None, "error": "the records could not be read here; the tracker poller writes them again on its next pass"}
    return JSONResponse(d, headers={"Cache-Control": "no-store"})


RECORDS_ROUTES = [Route("/api/records", api_records)]
