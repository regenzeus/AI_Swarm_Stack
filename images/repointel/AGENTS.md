# images/repointel/: CodeLore and repowise, sealed

The two programs behind a repository's facts (`docs/REPO-KNOWLEDGE.md`): CodeLore reads the git history, repowise indexes
the code. `ops/repofacts.py` runs each of them in its own `docker run --rm` with no network, no capabilities and a read-only
root, on a throwaway copy of one repository. They never see the real clone, no secret and no model. A deploy rebuilds the
image when this directory changes; `make facts-image` does it by hand.

- **Pins.** CodeLore by version and by the SHA-256 of its release, checked against the release's `SHA256SUMS` at build.
  repowise and everything it brings by `requirements.lock`. Changing a pin is a decision (`UPGRADE.md`): also bump the tag
  `IMAGE` in `ops/repofacts.py` and in the `Makefile`.
- **Licences.** repowise is AGPL-3.0 and CodeLore GPL-3.0; the stack is MIT. They run as separate programs, and the stack
  neither imports nor bundles them. Take a proper look before anyone redistributes this image.
- Runs as uid 10001, so what it leaves in the copy is not the host user's: `ops/repofacts.py` clears the copy through the image.
