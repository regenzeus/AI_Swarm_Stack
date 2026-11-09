"""What may enter a run's history, and how it is stored (GEN-36, docs/AI-STACK.md §3).

Temporal keeps the input and output of every workflow, activity, signal and query in its database, which is in the
stack's Postgres. Two layers keep content out of it:

- **References only, on a customer-class deployment.** The payload converter refuses bytes, any string longer than
  STRING_MAX, and any payload larger than PAYLOAD_MAX: those are content (a file, an extract, a diff, item text, a
  model's answer), and content stays in the artifact store and the worker folders, which keep their data class. A
  run passes references: an artifact's hash, a path, a ticket key, a commit, a verdict's pass and its problem count.
  The structures the engine itself passes (a pinned graph, a run's state) are registered with STRUCTURES: they may be
  larger, up to STRUCTURE_MAX, but their strings are still capped. Home's data is personal, so home is not strict.
- **Encrypted everywhere.** The codec encrypts every payload with AES-GCM under the deployment's key (the secret
  TEMPORAL_CODEC_KEY, 32 bytes, base64), tagged with the key's id. Without the key a payload is ciphertext, in the
  database, in a backup and in Temporal's web UI; the UI decodes only through the codec server, behind the app's gate.

    data_converter(customer=..., key=...)   the converter a client and its workers use
    key_from_env()                          the deployment's key, or a refusal that says what is missing
"""
import base64
import dataclasses
import hashlib
import os

import temporalio.converter
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from temporalio.api.common.v1 import Payload

from engine.shapes import STRUCTURES, structure  # noqa: F401  (structure: registered shapes, re-exported for callers)

ENCODING = b"binary/aistack-aesgcm"
KEY_ENV = "TEMPORAL_CODEC_KEY"
# limit: refuses, a customer-class payload above this is content, not a reference (GEN-36)
PAYLOAD_MAX = 4096
# limit: refuses, a customer-class string above this is content: a reference is a hash, a path, a key or a word
STRING_MAX = 300
# limit: refuses, the engine's own structures (a pinned graph, a run's state) above this are not a template's
STRUCTURE_MAX = 512 * 1024


class ContentRefused(ValueError):
    """A payload that would put content into a customer-class history."""


def _strings(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _strings(v)


def why_content(value):
    """None when value may enter a customer-class history as a reference; else why it is content."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "bytes are content"
    long = next((s for s in _strings(value) if len(s) > STRING_MAX), None)   # limit: refuses, a long string is content (GEN-36)
    if long is not None:
        return f"a string of {len(long)} characters is content (a reference is at most {STRING_MAX})"
    return None


class ReferencesOnly(temporalio.converter.DefaultPayloadConverter):
    """The default JSON converter, refusing content (a customer-class deployment's)."""

    def to_payloads(self, values):
        for v in values:
            why = why_content(v)
            if why:
                raise ContentRefused(f"refused by the data guard (GEN-36): {why}; pass a reference instead "
                                     f"(an artifact's hash, a path, a ticket key)")
        out = super().to_payloads(values)
        for v, p in zip(values, out):
            cap = STRUCTURE_MAX if type(v) in STRUCTURES else PAYLOAD_MAX
            if len(p.data) > cap:
                raise ContentRefused(f"refused by the data guard (GEN-36): a payload of {len(p.data)} bytes is content "
                                     f"(at most {cap}); pass a reference instead")
        return out


class Encrypting(temporalio.converter.PayloadCodec):
    """AES-GCM over each whole payload (its metadata too), under the deployment's key, tagged with the key's id."""

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("the codec's key must be 32 bytes")
        self.aes = AESGCM(key)
        self.kid = hashlib.sha256(key).hexdigest()[:12].encode()

    async def encode(self, payloads):
        out = []
        for p in payloads:
            nonce = os.urandom(12)
            out.append(Payload(metadata={"encoding": ENCODING, "aistack-key": self.kid},
                               data=nonce + self.aes.encrypt(nonce, p.SerializeToString(), self.kid)))
        return out

    async def decode(self, payloads):
        out = []
        for p in payloads:
            if p.metadata.get("encoding") != ENCODING:
                out.append(p)                 # not ours (Temporal's own, or written before the codec): as it is
                continue
            kid = p.metadata.get("aistack-key", b"")
            if kid != self.kid:
                raise ValueError(f"a payload encrypted with key {kid.decode() or '?'} cannot be read with key {self.kid.decode()}")
            out.append(Payload.FromString(self.aes.decrypt(p.data[:12], p.data[12:], self.kid)))
        return out


def key_from_env(env=os.environ):
    """The deployment's 32-byte key from TEMPORAL_CODEC_KEY (base64). Refuses, saying what is wrong, never what it is."""
    raw = env.get(KEY_ENV, "").strip()
    if not raw:
        raise SystemExit(f"the engine needs {KEY_ENV} (32 random bytes, base64) in the deployment's secrets: "
                         f"it never stores a run unencrypted")
    try:
        key = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_" if ("-" in raw or "_" in raw) else None, validate=True)
    except ValueError:
        raise SystemExit(f"{KEY_ENV} is not base64") from None
    if len(key) != 32:
        raise SystemExit(f"{KEY_ENV} holds {len(key)} bytes, and the codec needs 32")
    return key


def new_key():
    """A fresh key for TEMPORAL_CODEC_KEY (the setup's, written straight into the secrets, never printed in a log)."""
    return base64.b64encode(os.urandom(32)).decode()


def data_converter(customer: bool, key: bytes):
    """The converter of this deployment: references only when it holds customer data, and always encrypted."""
    base = temporalio.converter.DataConverter.default
    if customer:
        base = dataclasses.replace(base, payload_converter_class=ReferencesOnly)
    return dataclasses.replace(base, payload_codec=Encrypting(key))
