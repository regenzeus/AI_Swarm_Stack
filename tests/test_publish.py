"""The public snapshot (SEC-19, FND-75): every identifier from the private map is replaced, the encrypted secrets are
left out with examples that name their values, hashes and generated files follow the public text, and a snapshot
that still holds anything personal is stopped before its tests or a push. The fixtures are built from pieces, so
this file holds nothing the scan of the real snapshot would stop on."""
import hashlib
import io
import json
import tarfile
import types

import publish as P

AT = "@"
LAN = "192.168."
TERMS = [("jdoe7" + AT + "mail.test", "owner@example.com"), ("Jane Doe", "Alex Example"), ("Jane", "the owner"),
         ("jane", "owner"), (LAN + "77.", LAN + "1.")]


def test_terms_are_replaced_as_whole_words_and_only_a_capitalised_sentence_start_is_capitalised():
    text = ("Jane approves. Ask jane" + AT + "test; \"Jane's Gmail\"; janet stays; signed by Jane.\n"
            "- Jane Doe signs at " + LAN + "77.80\n| POST | Jane pastes her token |")
    assert P.redact(text, TERMS) == ("The owner approves. Ask owner" + AT + "test; \"The owner's Gmail\"; janet stays; "
                                     "signed by the owner.\n- Alex Example signs at " + LAN + "1.80\n"
                                     "| POST | The owner pastes her token |")
    assert P.redact('by="jane"', TERMS) == 'by="owner"'           # code compares it: a lowercase term keeps its case
    assert P.redact('"a\\n\\nJane at ' + LAN + '77.80"', TERMS) == '"a\\n\\nthe owner at ' + LAN + '1.80"'   # JSON escapes


def test_the_scan_names_every_leftover_without_printing_the_term_and_lets_placeholders_pass(monkeypatch):
    left = {"a.md": "Call JANE now",
            "b.py": "to = 'someone" + AT + "real.de'\nnas = '" + LAN + "77.5'\nurl = 'https://box.tail9z9" + ".ts.net'",
            "c.txt": "key = gh" + "p_" + "A" * 24 + "\nrecipient: age1" + "q" * 58 + "\nv: ENC" + "[AES256_GCM,data:x]",
            "jane-notes.md": "nothing", "e.json": '"x\\n' + LAN + '77.80"', "f.md": "the phone janes-s22", "g.md": "a mjane-v2 model"}
    probs = P.scan(left, TERMS)
    for want in ("a.md:1: private term #4 of the map", "b.py:1: e-mail address", "b.py:2: LAN address", "b.py:3: tailnet name",
                 "c.txt:1: token", "c.txt:2: age recipient", "c.txt:3: sops value", "jane-notes.md: the file name holds a private term",
                 "e.json:1: LAN address", "f.md:1: private term #3"):
        assert any(p.startswith(want) for p in probs), want
    assert not any("jane" in p.lower().replace("jane-notes.md", "") for p in probs)
    monkeypatch.setattr(P, "ALLOW_WORDS", {"mjane"})            # a word that holds a term by chance, named
    assert not any(p.startswith("g.md") for p in P.scan(left, TERMS)) and any(p.startswith("g.md") for p in probs)
    clean = {"d.md": "owner" + AT + "example.com at " + LAN + "1.80, " + LAN + "0.0/16, pc.example" + ".ts.net, 100.64.0.10"}
    assert P.scan(clean, TERMS) == []


def archive(files, modes=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), (modes or {}).get(name, 0o644)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_the_snapshot_leaves_out_the_secrets_and_follows_the_public_text(tmp_path):
    bench = "q: Which NAS does Jane have, at " + LAN + "77.80?\n"
    files, executable = P.build(terms=TERMS, archive=archive({
        "secrets/secrets.enc.yaml": "API_KEY: ENC" + "[AES256_GCM,data:x]\nMAIL_TO: ENC" + "[AES256_GCM,data:y]\nsops:\n  age: []\n",
        ".sops.yaml": "creation_rules:\n  - age: age1" + "q" * 58 + "\n",
        "eval/bench-v1.yaml": bench,
        "eval/FROZEN.sha256": hashlib.sha256(bench.encode()).hexdigest() + "  bench-v1.yaml\n",
        "ops/run.sh": "echo jane\n"}, modes={"ops/run.sh": 0o755}))
    assert "secrets/secrets.enc.yaml" not in files and executable == {"ops/run.sh"}
    assert files["secrets/secrets.example.yaml"].endswith('API_KEY: ""\nMAIL_TO: ""\n') and "ENC" not in files["secrets/secrets.example.yaml"]
    assert "age1" not in files[".sops.yaml"] and "<your age public key" in files[".sops.yaml"]
    assert files["eval/bench-v1.yaml"] == "q: Which NAS does the owner have, at " + LAN + "1.80?\n"
    assert files["eval/FROZEN.sha256"].split()[0] == hashlib.sha256(files["eval/bench-v1.yaml"].encode()).hexdigest()
    assert files["ops/run.sh"] == "echo owner\n" and P.scan(files, TERMS) == []
    out = P.write(files, executable, tmp_path / "tree")
    assert out == files and (tmp_path / "tree/ops/run.sh").stat().st_mode & 0o111 and not (tmp_path / "tree/.sops.yaml").stat().st_mode & 0o111


def test_the_push_refuses_when_git_would_leave_out_a_file_of_the_snapshot(tmp_path, monkeypatch):
    import subprocess
    tree, repo = tmp_path / "tree", tmp_path / "repo"
    files = {".gitignore": "secrets/*.yaml\n", "secrets/secrets.example.yaml": 'API_KEY: ""\n', "README.md": "hi\n"}
    P.write(files, set(), tree)
    monkeypatch.setattr(P, "WORK", tmp_path)
    monkeypatch.setattr(P, "REMOTE", str(tmp_path / "none.git"))           # never reached: it stops before a push
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", P.REMOTE], check=True)
    monkeypatch.setattr(P, "subprocess", types.SimpleNamespace(**{**vars(subprocess), "run": lambda a, **k: (
        subprocess.CompletedProcess(a, 0, "", "") if "ls-remote" in a else subprocess.run(a, **k))}))
    try:
        P.push(tree, "HEAD")
        raise AssertionError("pushed")
    except SystemExit as e:
        assert "git would commit 2 files, the snapshot has 3: secrets/secrets.example.yaml" in str(e)


def test_a_snapshot_with_a_leftover_runs_no_tests_and_pushes_nothing(tmp_path, monkeypatch):
    rows = []
    monkeypatch.setattr(P, "WORK", tmp_path)
    monkeypatch.setattr(P, "committed", lambda: "0" * 40)
    monkeypatch.setattr(P, "load_map", lambda: TERMS)
    monkeypatch.setattr(P, "build", lambda head, terms, assets=None: ({"a.md": "JANE was here"}, set()))
    monkeypatch.setattr(P, "tests", lambda dest: (_ for _ in ()).throw(AssertionError("tests ran")))
    monkeypatch.setattr(P, "push", lambda dest, head: (_ for _ in ()).throw(AssertionError("pushed")))
    monkeypatch.setattr(P, "record", lambda **r: rows.append(r))
    assert P.main("push") == 1 and rows[0]["result"] == "stopped" and rows[0]["problems"] == 2    # "Jane" and "jane"
    assert not (tmp_path / "tree").exists()                       # nothing personal stays on disk either
    assert json.dumps(rows).lower().count("jane") == 0


def test_images_come_only_from_one_folder_and_hide_nothing(tmp_path):
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in {"docs/screenshots/a.jpg": jpg, "README.md": b"Jane's page"}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    assets = {}
    files, executable = P.build(terms=TERMS, archive=buf.getvalue(), assets=assets)
    assert assets == {"docs/screenshots/a.jpg": jpg} and "docs/screenshots/a.jpg" not in files and files["README.md"] == "The owner's page"
    P.write(files, executable, tmp_path / "t", assets)
    assert (tmp_path / "t/docs/screenshots/a.jpg").read_bytes() == jpg                     # byte for byte, no text rewrite
    assert P.asset_problems({"docs/screenshots/a.jpg": jpg}) == []
    assert P.asset_problems({"docs/screenshots/a.png": jpg})[0].endswith("not an image of an allowed kind")
    assert P.asset_problems({"docs/screenshots/a.gif": b"GIF89a"})[0].endswith("not an image of an allowed kind")
    assert P.asset_problems({"docs/screenshots/a.jpg": jpg + b"Exif"})[0].endswith("holds metadata")
    assert "at most" in P.asset_problems({"docs/screenshots/a.jpg": jpg + b"\x00" * P.ASSET_MAX})[0]
    assert any(p.startswith("docs/screenshots/jane.jpg") for p in P.scan({"docs/screenshots/jane.jpg": ""}, TERMS))   # a name is still scanned
    other = io.BytesIO()
    with tarfile.open(fileobj=other, mode="w") as tar:
        info = tarfile.TarInfo("docs/photo.jpg")
        info.size = len(jpg)
        tar.addfile(info, io.BytesIO(jpg))
    try:
        P.build(terms=TERMS, archive=other.getvalue(), assets={})
        raise AssertionError("a binary outside the folder must stop the snapshot")
    except UnicodeDecodeError:
        pass
