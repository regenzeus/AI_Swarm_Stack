# images/pkgproxy/: package-registry proxy

tinyproxy (`tinyproxy.conf`) with an allow-list (`allow.txt`). Sandboxes (builder, OpenCode) can `npm install` /
`pip install` from the public registries and nothing else. This is how they get packages without general internet.

`allow-builder.txt` is the builder's own list (compose service `pkgproxy-builder`): the same registries plus
`api.anthropic.com` for the Claude Code engine. OpenCode keeps `allow.txt`.

Adding a host to `allow.txt` widens what every sandbox can reach. Treat it as a security change: say why in the
commit, and prefer a registry mirror over a new domain.
