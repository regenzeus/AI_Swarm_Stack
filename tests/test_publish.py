"""The public snapshot (SEC-19, FND-75): every identifier from the private map is replaced, the encrypted secrets are
left out with examples that name their values, hashes and generated files follow the public text, and a snapshot
that still holds anything personal is stopped before its tests or a push. The fixtures are built from pieces, so
this file holds nothing the scan of the real snapshot would stop on."""
import hashlib
import io
import json
import subprocess

import pytest
import tarfile
import types
from pathlib import Path

import publish as P

ROOT = Path(__file__).resolve().parent.parent
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
    assert P.redact("description: 'Jane''s Gmail'; it's Jane's", TERMS) == "description: 'The owner''s Gmail'; it's the owner's"   # YAML
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


def test_the_push_commits_every_file_of_the_snapshot_whatever_its_gitignore_says(tmp_path, monkeypatch):
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
    with pytest.raises(subprocess.CalledProcessError):               # only the push itself fails: there is no remote here
        P.push(tree, "HEAD")
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.split()
    assert sorted(tracked) == [".gitignore", "README.md", "secrets/secrets.example.yaml"]   # the snapshot whole, its .gitignore notwithstanding


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


def test_an_address_written_as_a_regular_expression_is_still_found():
    """FND-124: the benchmark held the NAS's real address as a pattern, in every public commit, past every scan."""
    escaped = LAN.replace(".", "\\\\.") + "77\\\\.80"
    probs = P.scan({"bench.yaml": f'must_not: ["{escaped}"]', "mail.json": '"owner' + AT + 'example.com\\nFrom"'}, TERMS)
    assert any(p.startswith("bench.yaml:1: LAN address") for p in probs)
    assert not any(p.startswith("mail.json") for p in probs)   # a line break in JSON is no part of the address before it


def test_real_runs_stay_out_but_the_evidence_requirements_cite_stays(tmp_path):
    assert P.LEFT_OUT.match("eval/results/20261024-224644-baseline-v1.json")
    assert P.LEFT_OUT.match("eval/results/20261101-113137-trial-semver.json")
    for cited in ("20261031-140852-tasks-gate.json", "20261031-152501-conductor-gate.json", "20261101-020317-trigger-proof.json"):
        assert not P.LEFT_OUT.match(f"eval/results/{cited}")
        assert cited in "".join(f.read_text() for f in (ROOT / "requirements").glob("*.yaml"))
    assert not P.LEFT_OUT.match("eval/tasks-v1.yaml")


def test_a_fresh_publish_replaces_the_public_history(tmp_path, monkeypatch):
    bare = tmp_path / "public.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    monkeypatch.setattr(P, "REMOTE", str(bare))
    monkeypatch.setattr(P, "WORK", tmp_path / "work")
    monkeypatch.setattr(P, "ROOT", tmp_path / "private")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    (tmp_path / "private").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path / "private")], check=True)
    g = ["git", "-C", str(tmp_path / "private"), "-c", "user.name=a", "-c", "user.email=a@example.com"]
    subprocess.run([*g, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    dest = tmp_path / "tree"
    dest.mkdir()
    for text in ("one", "two"):
        (dest / "a.txt").write_text(text)
        assert P.push(dest, "HEAD")
    count = lambda: subprocess.run(["git", "--git-dir", str(bare), "rev-list", "--count", "main"], capture_output=True, text=True).stdout.strip()
    assert count() == "2"
    (dest / "a.txt").write_text("clean")
    assert P.push(dest, "HEAD", fresh=True)
    assert count() == "1"
    shown = subprocess.run(["git", "--git-dir", str(bare), "show", "main:a.txt"], capture_output=True, text=True).stdout
    assert shown == "clean"
    msg = subprocess.run(["git", "--git-dir", str(bare), "log", "-1", "--format=%B", "main"], capture_output=True, text=True).stdout
    assert "shares no history with the earlier ones" in msg and "rebase --onto origin/main" in msg    # a site knows to move, not pull


def test_every_landing_runs_the_privacy_scan_and_a_leak_stops_it(monkeypatch, tmp_path):
    land = (ROOT / "ops/land.sh").read_text()
    assert 'python3 ops/publish.py scan "$TIP"' in land and "NOT LANDED: the privacy scan stopped it" in land
    assert land.index("publish.py scan") < land.index("git merge -q --ff-only")      # before main moves
    monkeypatch.setattr(P, "MAP", tmp_path / "no-map")
    assert P.scan_only("HEAD") == []                                                  # a machine without the map has nothing to compare
    (tmp_path / "map").write_text("Jane\tthe owner\n")
    monkeypatch.setattr(P, "MAP", tmp_path / "map")
    monkeypatch.setattr(P, "build", lambda head, terms, assets=None: ({"a.md": "x" + AT + "leak.example.de"}, set()))
    assert any(x.startswith("a.md:1: e-mail address") for x in P.scan_only("HEAD"))


def test_a_generated_file_stays_what_its_generator_makes_after_the_name_swap():
    """The public copy runs deployments/example-work's up-to-date check on swapped text: a longer replacement must not
    move a line break of the generated YAML (8 Nov: the publish stopped on it)."""
    import yaml
    cfg = {"mcp_servers": {"mail": {"description": "Jane's Gmail: search, read, label, archive and mark mail; only what Jane granted, and nothing else at all"}}}
    dump = lambda c: yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=10**6)
    swapped = yaml.safe_load(P.redact(dump(cfg), TERMS))
    assert P.redact(dump(cfg), TERMS) == dump(swapped)
