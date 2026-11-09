"""The scout's page reader (images/fetch/fetch_pdf.py): a page served gzip-compressed reads as text. Overnight exercise, 8 Nov 2026:
the streaming rewrite rebuilt the response from bytes httpx had already decoded but kept "Content-Encoding: gzip", so httpx
decoded them again and every gzip site failed ("incorrect header check": python.org, geizhals.de, amazon.de, 43 times)."""
import ast
import gzip
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "images/fetch/fetch_pdf.py").read_text()


def plain_headers():
    tree = ast.parse(SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "plain_headers")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "fetch_pdf.py", "exec"), ns)  # nosemgrep: python-eval-exec -- the module's own function, from its source
    return ns["plain_headers"]


def test_a_gzip_page_rebuilt_from_decoded_bytes_reads_as_text():
    httpx = pytest.importorskip("httpx")
    wire = httpx.Headers({"content-encoding": "gzip", "content-length": "20", "content-type": "text/html"})
    decoded = b"<html><body>Python 3.15.2</body></html>"
    with pytest.raises(httpx.DecodingError):                                     # what the reader did: the bytes decoded twice
        httpx.Response(200, headers=wire, content=decoded).read()
    r = httpx.Response(200, headers=plain_headers()(wire), content=decoded)
    assert r.text == decoded.decode() and r.headers["content-type"] == "text/html"
    assert gzip.decompress(gzip.compress(decoded)) == decoded


def test_the_reader_rebuilds_its_response_with_plain_headers():
    assert "head = Response(resp.status_code, headers=plain_headers(resp.headers), content=bytes(body)" in SRC
