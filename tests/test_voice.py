"""Hermes' voice at home (docs/HOME-VOICE.md): the speech services on the NAS and their measurement."""
import io
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))
import voice_bench as VB  # noqa: E402


def test_the_speech_services_listen_on_the_nas_only_and_keep_small_logs():
    """VOI-01"""
    c = yaml.safe_load((ROOT / "nas/voice/compose.yaml").read_text())
    for name, s in c["services"].items():
        assert all(p.startswith("127.0.0.1:") for p in s["ports"]), name
        assert "@sha256:" in s["image"] and s["logging"]["options"] == {"max-size": "1m", "max-file": "1"}, name
        assert "no-new-privileges:true" in s["security_opt"] and s.get("mem_limit"), name
        assert "network_mode" not in s, name                  # never the host network: only the ports above
    assert "ssh synology" in (ROOT / "ops/deploy-voice.sh").read_text()


class FakeSock:
    def __init__(self):
        self.sent = b""

    def sendall(self, b):
        self.sent += b


def test_the_bench_speaks_wyoming_and_scores_words():
    """VOI-02: a header line with inline data and the payload after it; data_length is read too; words are scored
    without case or punctuation."""
    s = FakeSock()
    VB.send(s, "audio-chunk", {"rate": 16000}, b"\x01\x02")
    head, rest = s.sent.split(b"\n", 1)
    assert json.loads(head) == {"type": "audio-chunk", "data": {"rate": 16000}, "payload_length": 2} and rest == b"\x01\x02"
    extra = json.dumps({"text": "Turn off the lights."}).encode()
    f = io.BytesIO(json.dumps({"type": "transcript", "data_length": len(extra)}).encode() + b"\n" + extra)
    assert VB.recv(f) == ("transcript", {"text": "Turn off the lights."}, b"")
    assert VB.wer("turn off the lights in the living room", "Turn off the lights in the living-room.") == (0, 8)
    assert VB.wer("how much space is left on the NAS", "how much space is left on the NES") == (1, 8)
    quiet = b"\x00\x10" * 400
    assert VB.noisy(quiet, 20, 1) == VB.noisy(quiet, 20, 1) != quiet          # repeatable noise, not silence
    assert VB.pct([5, 1, 3], 50) == 3
