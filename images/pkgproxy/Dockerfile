# Package-registry proxy for OpenCode: lets `npm install` / `pip install` reach the public registries and
# nothing else (tinyproxy, default deny, CONNECT to port 443 only). It sits on its own network with OpenCode, so
# no other container gains an internet route through it.
FROM alpine:3.20
RUN apk add --no-cache tinyproxy && adduser -D -u 10004 proxy
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allow.txt /etc/tinyproxy/allow.txt
USER proxy
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
