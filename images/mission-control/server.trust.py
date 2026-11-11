# part of server.py (PLT-25; SEC-24, SEC-25, SEC-26; review 10 Nov O1, O2): who may speak to the app at all. It runs in
# server.py's namespace where it stood (_part); not a module of its own.
#
# The app's identity (the owner's Tailscale login, or this PC's local gate) is believed only on the path the owner's
# browser takes: tailscale serve on Windows -> wslrelay -> WSL's 127.0.0.1:8090 -> Docker's published port. Docker's
# port publishing (docker-proxy) connects to the container from the gateway of the network that publishes the port, and
# Docker publishes ports on the network that is the container's default route (its gateway endpoint). Measured on the
# home PC, 11 Nov 2026 (rootless Docker 29.9.2, rootlesskit builtin port driver, docker-proxy on; docs/SECURITY.md):
#   the WSL host, Windows' localhost, tailscale serve :8447 and a container with --network host  -> 172.27.0.1 (mcui's
#   gateway, the default route in the app);  n8n (stepnet) -> 172.30.128.3;  Phoenix (obs) -> 172.22.0.2;
#   LiteLLM (mcnet) -> 172.26.0.4. Docker numbers its networks when it makes them, so the rule is the gateway the
#   container's own route table names (/proc/net/route), read at start and again when a request's peer differs.
# The MCP servers (8091, 8092, 8094, 8096, 8097, 8098, 8100) answer only LiteLLM (Docker's DNS names the peer) with the
# server's own bearer token; the step service (8099) only the AI Stack step node with its token.
#
# APP_TRUST (the deployment's setting, compose: ${APP_TRUST:-log}): log refuses nothing and logs every request it would
# refuse ("trust (log mode): would refuse ..."); on refuses them. A wrong rule locks the owner out, so a deployment runs
# a deploy in log mode first, and the lead switches it on (docs/SECURITY.md, "Switching the trust boundary on").
import socket
import struct

def trust_on(value):
    """APP_TRUST: on refuses; anything else (log, empty, a typo) only logs, so a typo never locks the owner out."""
    return str(value or "").strip().lower() == "on"


TRUST_ON = trust_on(os.environ.get("APP_TRUST", "log"))
ROUTE = Path("/proc/net/route")
_gate = {"addr": None}
MCP_TOKENS = {"missions": "MCP_TOKEN_MISSIONS", "claude": "MCP_TOKEN_CLAUDE", "house": "MCP_TOKEN_HOUSE", "files": "MCP_TOKEN_FILES",
              "memory": "MCP_TOKEN_MEMORY", "memorypublic": "MCP_TOKEN_MEMORYPUBLIC", "stack": "MCP_TOKEN_STACK"}   # the server's name -> its token's (sops)
LITELLM = "litellm"                                  # the one caller of the MCP servers, by its service name
STEP_TOKEN = os.environ.get("AISTACK_STEP_TOKEN", "")


def default_gateway(route=None):
    """The gateway of the container's default route ('' when there is none): the address Docker's published port
    connects from (see above)."""
    try:
        for line in Path(route or ROUTE).read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 2 and f[1] == "00000000" and f[2] != "00000000":
                return socket.inet_ntoa(struct.pack("<I", int(f[2], 16)))
    except (OSError, ValueError):
        pass
    return ""


def gate_address():
    if _gate["addr"] is None:
        _gate["addr"] = default_gateway()
    return _gate["addr"]


def peer_of(scope):
    return ((scope.get("client") or ("", 0))[0]) or ""


def from_gate(scope):
    """-> True when the connection came through the app's published port (the gate path)."""
    peer = peer_of(scope)
    if peer and peer == gate_address():
        return True
    _gate["addr"] = default_gateway()                # a network change moves the default route: look once more
    return bool(peer) and peer == _gate["addr"]


def trust_refuses(what, scope):
    """-> True when this request is to be refused: always in on mode; in log mode never, and the would-be refusal is
    logged (docker logs aistack-mission-control-1) with what, the peer and the path."""
    if TRUST_ON:
        return True
    print(f"trust (log mode): would refuse {what} from {peer_of(scope) or 'an unknown peer'} for {scope.get('path', '')}"
          f" (the published port's address is {gate_address() or 'unknown'})", flush=True)
    return False


def bearer(scope):
    return dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")


def token_ok(scope, token):
    return bool(token) and hmac.compare_digest(bearer(scope).encode(), f"Bearer {token}".encode())


def peer_is(scope, service, resolve=None, reverse=None):
    """-> True when the peer is the stack's container of that service: its address as the service's name resolves here,
    or the container name Docker's DNS gives the address (<project>-<service>-<n>.<network>; a container on another
    shared network than the one the name resolves to)."""
    peer = peer_of(scope)
    if not peer:
        return False
    try:
        if peer in (resolve or socket.gethostbyname_ex)(service)[2]:
            return True
    except OSError:
        pass
    try:
        name = (reverse or socket.gethostbyaddr)(peer)[0].split(".")[0]
    except OSError:
        return False
    return bool(re.fullmatch(rf"[a-z0-9][a-z0-9_-]*[-_]{re.escape(service)}[-_]\d+", name))


async def _refuse(send, status, error):
    body = json.dumps({"error": error}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"),
                                                                           (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def mcp_guard(inner, name):
    """SEC-26: an MCP server's app, answering only LiteLLM with this server's own bearer token (MCP_TOKENS)."""
    env = MCP_TOKENS[name]

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            why = ""
            if not token_ok(scope, os.environ.get(env, "")):
                why = f"a call without the {name} server's token ({env})"
            elif not await asyncio.to_thread(peer_is, scope, LITELLM):     # Docker's DNS: a short lookup, off the loop
                why = f"a call from another container than {LITELLM}"
            if why and trust_refuses(f"{why} to the {name} MCP server", scope):
                return await _refuse(send, 401, f"refused: the {name} tools answer only the model gateway with their token (SEC-26)")
        return await inner(scope, receive, send)
    return guarded


def step_guard(inner):
    """SEC-25: the step service answers only a caller with its token (AISTACK_STEP_TOKEN, sent by the AI Stack step node)."""
    async def guarded(scope, receive, send):
        if scope["type"] == "http" and not token_ok(scope, STEP_TOKEN):
            if trust_refuses("a step without the step service's token (AISTACK_STEP_TOKEN)", scope):
                return await _refuse(send, 401, "refused: the step service answers only n8n's AI Stack step with its token (SEC-25)")
        return await inner(scope, receive, send)
    return guarded


print(f"trust: mode {'on' if TRUST_ON else 'log'}; the published port's address {gate_address() or 'unknown'};"
      f" step token {'set' if STEP_TOKEN else 'MISSING'}; MCP tokens missing: "
      f"{', '.join(n for n, e in MCP_TOKENS.items() if not os.environ.get(e)) or 'none'}", flush=True)
