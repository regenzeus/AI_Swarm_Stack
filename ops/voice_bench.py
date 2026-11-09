"""Hermes' voice, phase V0 (docs/HOME-VOICE.md): measure speech to text (Whisper) and text to speech (Piper) on the NAS.

Speaks the Wyoming protocol with the standard library only (the NAS has Python 3.8), so it runs on the NAS itself,
where both services listen on 127.0.0.1:
  ssh synology python3 - describe < ops/voice_bench.py          is each service up (exit 1 if not)
  ssh synology python3 - bench [noise_db] < ops/voice_bench.py  the V0 measurement, one JSON report on stdout

The spoken samples are synthesised by Piper in three voices other than Hermes' own, with white noise added (20 dB
below the speech by default): repeatable, but cleaner than a real room; V1 repeats it with the owner's voice.
Nothing is stored: the audio lives in memory for the run.
"""
import array
import json
import math
import random
import re
import socket
import sys
import time

WHISPER, PIPER = ("127.0.0.1", 10300), ("127.0.0.1", 10200)
SAMPLE_VOICES = ["en_US-ryan-medium", "en_US-amy-medium", "en_GB-northern_english_male-medium"]
HERMES_VOICES = ["en_GB-alba-medium", "en_US-lessac-medium", "en_GB-cori-medium"]
SAMPLES = [                                        # what one says to Hermes at home (numbers as words: the scoring is exact)
    "Hermes what is on my calendar tomorrow morning",
    "turn off the lights in the living room",
    "how much space is left on the NAS",
    "start a research on mesh repeaters for my router and send me the result",
    "what did the scout find about the chip shortage",
    "remind me to call my mother at six in the evening",
    "is the internet slow right now",
    "read me the summary of my newest briefing",
    "pause the weekly news mission",
    "what is the weather going to be like this weekend",
    "add milk and eggs to the shopping list",
    "who is at home right now",
    "tell me more about that",
    "no I meant the other one",
    "how long does a soft boiled egg take",
    "write a short newsletter about electric cars in China",
    "what happened with the build that failed this morning",
    "set the bedroom lights to thirty percent",
    "thanks that is all for now",
    "let us talk about my plans for the weekend",
]
ANSWERS = [                                        # what Hermes says back, for the voices' speed
    "On it. I'll tell you when the research is ready.",
    "The NAS has five point two terabytes free, which is about sixty eight percent of the volume.",
    "Your weekly news mission is paused. Say resume it when you want it back.",
    "Tomorrow you have a dentist appointment at nine, and the call with Peter at eleven thirty.",
    "The scout found that memory chips are the tightest: prices rose about twenty percent since August, and "
    "analysts expect the shortage to last into next spring. Shall I go on?",
]


# ---------- the Wyoming protocol: a JSON header line, then optional data and payload bytes ----------
def send(sock, kind, data=None, payload=b""):
    head = {"type": kind, "data": data or {}}
    if payload:
        head["payload_length"] = len(payload)
    sock.sendall((json.dumps(head) + "\n").encode() + payload)


def recv(f):
    line = f.readline()
    if not line:
        raise EOFError("the service closed the connection")
    head = json.loads(line)
    data = head.get("data") or {}
    if head.get("data_length"):
        data.update(json.loads(f.read(head["data_length"])))
    payload = f.read(head["payload_length"]) if head.get("payload_length") else b""
    return head["type"], data, payload


def connect(addr, timeout=120):
    s = socket.create_connection(addr, timeout=timeout)
    return s, s.makefile("rb")


def describe(addr):
    s, f = connect(addr, 10)
    try:
        send(s, "describe")
        while True:
            kind, data, _ = recv(f)
            if kind == "info":
                return data
    finally:
        s.close()


def tts(text, voice):
    """-> (pcm, rate, ms to the first audio, ms in all)"""
    s, f = connect(PIPER)
    t0 = time.time()
    first, pcm, rate = None, bytearray(), 22050
    try:
        send(s, "synthesize", {"text": text, "voice": {"name": voice}})
        while True:
            kind, data, payload = recv(f)
            if kind == "audio-start":
                rate = data.get("rate", rate)
            elif kind == "audio-chunk":
                if first is None:
                    first = time.time()
                pcm += payload
            elif kind == "audio-stop":
                break
    finally:
        s.close()
    end = time.time()
    return bytes(pcm), rate, round(((first or end) - t0) * 1000), round((end - t0) * 1000)


def stt(pcm, rate):
    """-> (text, ms from the end of speech to the transcript)"""
    s, f = connect(WHISPER)
    fmt = {"rate": rate, "width": 2, "channels": 1}
    try:
        send(s, "transcribe", {"language": "en"})
        send(s, "audio-start", fmt)
        step = 2048 * 2
        for i in range(0, len(pcm), step):
            send(s, "audio-chunk", fmt, pcm[i:i + step])
        t0 = time.time()
        send(s, "audio-stop")
        while True:
            kind, data, _ = recv(f)
            if kind == "transcript":
                return data.get("text", ""), round((time.time() - t0) * 1000)
    finally:
        s.close()


def noisy(pcm, snr_db, seed):
    a = array.array("h", pcm)
    if not a:
        return pcm
    rms = math.sqrt(sum(x * x for x in a) / len(a))
    sigma, rnd = rms / (10 ** (snr_db / 20)), random.Random(seed)
    return array.array("h", (max(-32768, min(32767, int(x + rnd.gauss(0, sigma)))) for x in a)).tobytes()


def words(text):
    return re.sub(r"[^a-z0-9' ]", " ", text.lower().replace("-", " ")).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def bench(snr_db=20.0):
    out = {"whisper": describe(WHISPER).get("asr", [{}])[0].get("models", [{}])[0].get("name"), "noise_db": snr_db,
           "samples": [], "voices": {}}
    errs = total = 0
    for i, text in enumerate(SAMPLES):
        pcm, rate, _, _ = tts(text, SAMPLE_VOICES[i % len(SAMPLE_VOICES)])
        heard, ms = stt(noisy(pcm, snr_db, i), rate)
        e, n = wer(text, heard)
        errs, total = errs + e, total + n
        out["samples"].append({"said": text, "heard": heard.strip(), "speech_s": round(len(pcm) / 2 / rate, 1), "ms": ms, "word_errors": e})
    ms = [x["ms"] for x in out["samples"]]
    out["stt"] = {"word_error_rate": round(errs / total, 3), "exact": sum(1 for x in out["samples"] if not x["word_errors"]),
                  "of": len(SAMPLES), "ms_median": pct(ms, 50), "ms_slowest": max(ms)}
    for v in HERMES_VOICES:
        runs = []
        for text in ANSWERS:
            pcm, rate, first, all_ms = tts(text, v)
            runs.append({"first_ms": first, "ms": all_ms, "speech_s": round(len(pcm) / 2 / rate, 1)})
        out["voices"][v] = {"first_audio_ms_median": pct([r["first_ms"] for r in runs], 50),
                            "first_audio_ms_slowest": max(r["first_ms"] for r in runs),
                            "realtime_factor": round(sum(r["ms"] for r in runs) / 1000 / sum(r["speech_s"] for r in runs), 3)}
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "describe"
    if cmd == "describe":
        ok = True
        for name, addr in (("whisper", WHISPER), ("piper", PIPER)):
            try:
                describe(addr)
                print(name, "up")
            except (OSError, EOFError, ValueError) as e:
                ok = False
                print(name, "down:", e)
        sys.exit(0 if ok else 1)
    if cmd == "bench":
        print(json.dumps(bench(float(sys.argv[2]) if len(sys.argv) > 2 else 20.0), indent=1))
