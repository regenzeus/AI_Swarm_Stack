# Port forwarder: lets Docker publish a port for a service that sits only on the internal network.
# The service keeps no internet route; this container can only relay TCP to the one target it is given.
FROM alpine:3.20
RUN apk add --no-cache socat && adduser -D -u 10003 fwd
USER fwd
ENTRYPOINT ["sh", "-c", "exec socat TCP-LISTEN:${LISTEN_PORT},fork,reuseaddr TCP:${TARGET}"]
