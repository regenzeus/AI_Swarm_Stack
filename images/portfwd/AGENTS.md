# images/portfwd/: port forwarder

A tiny forwarder that lets Docker publish a `127.0.0.1` port for a service that sits only on an internal network,
such as OpenCode (`LISTEN_PORT` / `TARGET` in `compose/apps.yaml`, network `codeui`). Use it instead of putting
the service itself on a published network.
