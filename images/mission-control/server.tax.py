# part of server.py (TAX-10, TAX-11, docs/TAX-DESK.md): the tax desk's result per year for the owner's task "Your taxes".
# The runner shares it at /missions/tax/view.json with this app's user alone (a POSIX ACL, ops/tax_view.py); here it is
# served only to the owner's own signed-in session: never to the AI phone (PHN-07), never to the stack's own checks and
# previews (*@stack.local), never cached, never logged, and never part of the state every screen gets.
TAX_VIEW = M / "tax/view.json"


def tax_refusal(request):
    """None for the owner's own session, else the refusal (the gate before it has checked the sign-in)."""
    login = request.headers.get("tailscale-user-login", "")
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not on the AI phone: your tax figures show only on your own devices"}, status_code=403)
    if not login or login.endswith("@stack.local"):
        return JSONResponse({"ok": False, "error": "your tax figures show only to you, signed in"}, status_code=403)
    return None


async def api_tax(request):
    """TAX-10: every year the tax desk knows, as the runner shared it (ops/tax_view.py); none yet before its first run."""
    no = tax_refusal(request)
    if no:
        return no
    try:
        d = json.loads(await asyncio.to_thread(TAX_VIEW.read_text))
    except FileNotFoundError:
        d = {"years": [], "made": None}
    except (OSError, ValueError):                       # not shared with this app's user, or cut short: said, never shown half
        d = {"years": [], "made": None, "error": "the desk's result could not be read here; its next run writes it again"}
    return JSONResponse(d, headers={"Cache-Control": "no-store"})


TAX_ROUTES = [Route("/api/tax", api_tax)]
