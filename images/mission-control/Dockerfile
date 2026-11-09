# Mission Control: web app + API (8090) and MCP mission tools for Hermes (8091). See server.py.
FROM python:3.12-slim AS icons
RUN pip install --no-cache-dir pillow==11.0.0
COPY icons.py /icons.py
RUN python /icons.py /out

FROM python:3.12-slim
RUN pip install --no-cache-dir mcp==2.3.0 httpx==0.28.1 pywebpush==2.5.0 py-vapid==1.9.6 pyyaml==6.0.3 pypdf==5.1.0 python-docx==1.1.2 openpyxl==3.1.5 \
 && useradd -r -u 10006 mc
# Vendored front-end libraries and font (the app works without any CDN at runtime)
ADD https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js /app/web/static/vendor/marked.min.js
ADD https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js /app/web/static/vendor/purify.min.js
ADD https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js /app/web/static/vendor/d3.min.js
ADD https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5.0.20/files/inter-latin-wght-normal.woff2 /app/web/static/vendor/inter.woff2
ADD https://cdn.jsdelivr.net/npm/@fontsource-variable/archivo@5.2.5/files/archivo-latin-wdth-normal.woff2 /app/web/static/vendor/archivo.woff2
ADD https://cdn.jsdelivr.net/npm/@fontsource-variable/jetbrains-mono@5.2.5/files/jetbrains-mono-latin-wght-normal.woff2 /app/web/static/vendor/jetbrains-mono.woff2
COPY server.py server.*.py obs_core.py runrecord.py otlp.py textcap.py teamroom.py interactions.py /app/
COPY web /app/web
COPY guide /app/guide
COPY --from=icons /out /app/web/static/icons
RUN chmod -R a+rX /app
USER mc
EXPOSE 8090 8091 8092 8093
CMD ["python", "/app/server.py"]
