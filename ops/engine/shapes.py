"""The engine's own structures that may enter a run's history larger than a reference (GEN-36): a pinned graph, a run's
state. Kept apart from converter.py so that the graph model, and the Conductor that imports it until the cutover, need
neither Temporal's SDK nor cryptography."""
STRUCTURES = set()


def structure(cls):
    """Register one of the engine's own dataclasses as a known shape (converter.STRUCTURE_MAX applies, not PAYLOAD_MAX)."""
    STRUCTURES.add(cls)
    return cls
