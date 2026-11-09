# Repository facts: CodeLore and repowise, pinned, for ops/repofacts.py (docs/REPO-KNOWLEDGE.md, BLD-27).
# One-shot: `docker run --rm --network none`, each tool in its own run, with only a throwaway copy of one repository mounted.
# It must have no network, no secrets, no capabilities and never the real clone. No model features (--no-prose).
# Both are third-party programs, run and never imported: repowise is AGPL-3.0, CodeLore GPL-3.0, the stack MIT.
FROM python:3.12-slim-trixie AS codelore
# CodeLore needs glibc 2.39, hence trixie. The pinned sum must be the release's own and the download must match it.
ARG CODELORE=v0.30.0
ARG CODELORE_SHA256=11b2453f5ea94789b9eadf99f50634126d139de7f441d19a88874a60ccf0ee1f
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends ca-certificates curl >/dev/null \
 && mkdir /dl && cd /dl \
 && T="codelore-${CODELORE}-x86_64-unknown-linux-gnu.tar.gz" \
 && curl -fsSL -o "$T" "https://github.com/emrecdr/codelore/releases/download/${CODELORE}/$T" \
 && curl -fsSL -o SHA256SUMS "https://github.com/emrecdr/codelore/releases/download/${CODELORE}/SHA256SUMS" \
 && grep -qxE "${CODELORE_SHA256} +${T}" SHA256SUMS \
 && echo "${CODELORE_SHA256}  ${T}" | sha256sum -c - \
 && tar xzf "$T" && find . -type f -name codelore -exec install -m 755 {} /usr/local/bin/codelore \; \
 && codelore --version

FROM python:3.12-slim-trixie
COPY --from=codelore /usr/local/bin/codelore /usr/local/bin/codelore
COPY requirements.lock /tmp/requirements.lock
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git >/dev/null && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -q --disable-pip-version-check -r /tmp/requirements.lock && rm /tmp/requirements.lock \
 && useradd -r -u 10001 -d /tmp repointel \
 && git config --system safe.directory '*'
# safe.directory: the copy belongs to the host's user, the tools run as this one. DO_NOT_TRACK: repowise's telemetry is on by default.
ENV DO_NOT_TRACK=1 HOME=/tmp
USER 10001
WORKDIR /repo
