# part of server.py (GEN-33, GEN-36, docs/AI-STACK-PLAN.md §10 "Runs"): Temporal's own web UI inside the app, behind
# the app's front door, and the codec endpoint that lets it show decrypted payloads. The UI runs in the core
# (temporal-ui, TEMPORAL_UI_PUBLIC_PATH=/runs) on the engine network; the browser reaches it only through /runs here,
# so it has the app's gate. Its codec calls POST /api/codec/decode with the payloads it shows; this decrypts them with
# the deployment's key (TEMPORAL_CODEC_KEY), as ops/engine/converter.py's Encrypting does, and never encrypts.
import base64 as _b64
import hashlib as _hashlib

UI = os.environ.get("TEMPORAL_UI_URL", "http://temporal-ui:8080")
ENCODING = b"binary/aistack-aesgcm"


def _codec_key():
    raw = os.environ.get("TEMPORAL_CODEC_KEY", "").strip()
    if not raw:
        return None
    key = _b64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_" if ("-" in raw or "_" in raw) else None)
    return key if len(key) == 32 else None


async def api_codec_decode(request):
    """Temporal UI's codec protocol: {"payloads": [{"metadata": {k: base64}, "data": base64}]} -> the same, decrypted."""
    key = _codec_key()
    if key is None:
        return JSONResponse({"error": "no codec key on this deployment"}, status_code=503)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from temporalio.api.common.v1 import Payload
    aes, kid = AESGCM(key), _hashlib.sha256(key).hexdigest()[:12].encode()
    body = await request.json()
    out = []
    for p in body.get("payloads") or []:
        meta = {k: _b64.b64decode(v) for k, v in (p.get("metadata") or {}).items()}
        data = _b64.b64decode(p.get("data") or "")
        if meta.get("encoding") != ENCODING or meta.get("aistack-key") != kid:
            out.append(p)                                  # not ours, or another key's: shown as it is
            continue
        inner = Payload.FromString(aes.decrypt(data[:12], data[12:], kid))
        out.append({"metadata": {k: _b64.b64encode(v).decode() for k, v in inner.metadata.items()}, "data": _b64.b64encode(inner.data).decode()})
    return JSONResponse({"payloads": out})


async def runs_proxy(request):
    """/runs/...: Temporal's UI, passed through as it is (its pages, its API, its assets)."""
    path = request.url.path
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(request.method, f"{UI}{path}", params=request.query_params, content=await request.body(),
                            headers={k: v for k, v in request.headers.items() if k.lower() in ("content-type", "accept", "x-csrf-token", "cookie")})
    keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "cache-control", "set-cookie", "location")}
    return Response(r.content, status_code=r.status_code, headers=keep)
