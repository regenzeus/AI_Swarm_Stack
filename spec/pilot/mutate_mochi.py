"""Spec pilot: plant known deviations in a copy of mochi-mqtt (one line each, line count unchanged, still compiles
in spirit). The judge must find these; everything else is the control group.
  python3 spec/pilot/mutate_mochi.py <original repo> <mutant dir>   -> <mutant dir>/mutations.json"""
import json, shutil, sys
from pathlib import Path

MUTATIONS = [  # requirement, file, original line text, deviation, what changed
    ("MQTT-3.1.2-22", "clients.go", "time.Duration(keepalive+(keepalive/2))", "time.Duration(keepalive*3)",
     "keep-alive timeout 3x instead of 1.5x"),
    ("MQTT-3.3.1-1", "clients.go", "tk.FixedHeader.Dup = true", "tk.FixedHeader.Dup = false",
     "DUP flag not set on re-delivery"),
    ("MQTT-3.1.3-6", "clients.go", "cl.ID = xid.New().String()", "cl.ID = xid.New().String()[:2]",
     "assigned client id cut to 2 characters (not unique)"),
    ("MQTT-3.2.2-2", "server.go", "return false                           // [MQTT-3.2.2-3]",
     "return true                            // [MQTT-3.2.2-3]", "Session Present 1 although Clean Start"),
    ("MQTT-3.1.2-24", "clients.go", "uint32(buf.Len()) > pk.Mods.MaxSize {", "uint32(buf.Len()) > pk.Mods.MaxSize*2 {",
     "Maximum Packet Size enforced at twice the limit"),
    ("MQTT-3.3.1-5", "server.go", "if pk.FixedHeader.Retain { // [MQTT-3.3.1-5]",
     "if pk.FixedHeader.Retain && pk.FixedHeader.Qos > 0 { // [MQTT-3.3.1-5]", "QoS 0 retained messages not stored"),
    ("MQTT-3.3.2-2", "topics.go", "if strings.ContainsRune(filter, '+') || strings.ContainsRune(filter, '#') {",
     "if strings.ContainsRune(filter, '#') {", "'+' wildcard accepted in topic names"),
    # The broker checks this twice; the first run changed only topics.go, so the code still complied (the judge
    # rightly said "implemented"). Both checks now, a deviation spanning two files.
    ("MQTT-3.3.2-2", "packets/packets.go", 'strings.ContainsAny(pk.TopicName, "+#")',
     'strings.ContainsAny(pk.TopicName, "#")', "'+' wildcard accepted in topic names"),
]


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git"))
    done = []
    for rid, f, old, new, what in MUTATIONS:
        p = dst / f
        text = p.read_text()
        assert text.count(old) == 1, f"{rid}: pattern not unique in {f}"
        line = text[:text.index(old)].count("\n") + 1
        p.write_text(text.replace(old, new))
        done.append({"id": rid, "file": f, "line": line, "change": what})
    (dst / "mutations.json").write_text(json.dumps(done, indent=1))
    print(f"{len(done)} deviations planted in {dst}")


if __name__ == "__main__":
    main()
