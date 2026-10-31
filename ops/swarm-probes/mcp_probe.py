"""Phase 0 probe: a minimal MCP server (streamable HTTP, JSON responses) that reports what credential reached it.
It never echoes a credential, only the header names and a SHA-256 prefix of the Authorization value."""
import hashlib, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOL = {"name": "whoami", "description": "Report which credential reached this server (hash only).",
        "inputSchema": {"type": "object", "properties": {}}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, rid, result):
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "probe")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_response(405); self.end_headers()

    def do_DELETE(self):
        self.send_response(200); self.end_headers()

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        m, rid = msg.get("method"), msg.get("id")
        if rid is None:
            self.send_response(202); self.end_headers(); return
        if m == "initialize":
            return self.reply(rid, {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                                    "capabilities": {"tools": {}}, "serverInfo": {"name": "swarmprobe", "version": "0"}})
        if m == "tools/list":
            return self.reply(rid, {"tools": [TOOL]})
        if m == "tools/call":
            auth = self.headers.get("Authorization") or ""
            xkey = self.headers.get("X-Api-Key") or ""
            seen = {"auth_sha": hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else None,
                    "x_api_key_sha": hashlib.sha256(xkey.encode()).hexdigest()[:16] if xkey else None,
                    "headers": sorted(k.lower() for k in self.headers.keys())}
            return self.reply(rid, {"content": [{"type": "text", "text": json.dumps(seen)}]})
        return self.reply(rid, {})


ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
