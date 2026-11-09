"""mcp-server-fetch with PDF support: annual and quarterly reports, ASX announcements and many filings are PDFs, which
the stock server hands back as raw bytes. PDFs are turned into text page by page (pypdf); everything else is unchanged.
Paging works as before (start_index / max_length on the returned text). Run instead of `mcp-server-fetch`."""
import asyncio
import os
import io
import sys

from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData
import mcp_server_fetch.server as srv

MAX_BYTES, MAX_PAGES = 40 * 1024 * 1024, 400


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages[:MAX_PAGES], 1):  # cap: list (the text ends by saying how many pages were left)
        try:
            t = (page.extract_text() or "").strip()
        except Exception:
            t = ""
        if t:
            pages.append(f"--- page {i} ---\n{t}")
    # limit: drops, PDF pages past MAX_PAGES; the text says how many it has
    more = f"\n\n(only the first {MAX_PAGES} of {len(reader.pages)} pages)" if len(reader.pages) > MAX_PAGES else ""
    return "\n\n".join(pages) + more


def plain_headers(headers):
    """The headers for a response rebuilt from bytes httpx already decoded: without Content-Encoding (else httpx decodes the
    plain bytes again: "incorrect header check" on every gzip site, overnight exercise 8 Nov 2026) and the lengths of the wire."""
    return [(k, v) for k, v in headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]


async def fetch_url(url: str, user_agent: str, force_raw: bool = False, proxy_url: str | None = None):
    from httpx import AsyncClient, HTTPError, Response
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if (host == "sec.gov" or host.endswith(".sec.gov")) and os.environ.get("SEC_CONTACT"):
        user_agent = os.environ["SEC_CONTACT"]            # SEC fair-access policy: a contact in the User-Agent; sec.gov only
    async with AsyncClient(proxy=proxy_url) as client:
        try:
            async with client.stream("GET", url, follow_redirects=True, headers={"User-Agent": user_agent}, timeout=60) as resp:
                # limit: refuses, a page or PDF past what the fetch service's memory holds, with its size (review IMG-R8)
                if int(resp.headers.get("content-length") or 0) > MAX_BYTES:
                    raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"too large ({int(resp.headers['content-length']) // 1048576} MB; "
                                                                           f"at most {MAX_BYTES // 1048576} MB)"))
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:   # limit: refuses (no Content-Length, or a wrong one: counted while reading)
                        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"too large (more than {MAX_BYTES // 1048576} MB)"))
                head = Response(resp.status_code, headers=plain_headers(resp.headers), content=bytes(body), request=resp.request)
        except HTTPError as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url}: {e!r}"))
    if head.status_code >= 400:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url} - status code {head.status_code}"))
    ctype = head.headers.get("content-type", "").lower()
    if "application/pdf" in ctype or head.content[:5] == b"%PDF-":
        # limit: refuses, a PDF too big for the fetch service's memory, with its size
        if len(head.content) > MAX_BYTES:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"PDF too large ({len(head.content) // 1048576} MB)"))
        text = await asyncio.to_thread(pdf_text, head.content)
        if not text.strip():
            return "", "This PDF has no text layer (scanned images); its text cannot be read.\n"
        return text, f"PDF converted to text ({text.count('--- page ')} pages with text). Use start_index to read further.\n"
    page_raw = head.text                                  # the stock server's handling, on the same response
    if ("<html" in page_raw[:100] or "text/html" in ctype or not ctype) and not force_raw:  # cap: parse
        return srv.extract_content_from_html(page_raw), ""
    return page_raw, f"Content type {ctype} cannot be simplified to markdown, but here is the raw content:\n"


srv.fetch_url = fetch_url
try:                                       # bigger default chunk (5000 -> 20000 chars): a report in a few reads, not 15
    srv.Fetch.model_fields["max_length"].default = 20000
    srv.Fetch.model_rebuild(force=True)
except Exception as e:
    print("could not raise the default max_length:", e, file=sys.stderr)

if __name__ == "__main__":
    from mcp_server_fetch import main
    sys.argv[0] = "mcp-server-fetch"
    main()
