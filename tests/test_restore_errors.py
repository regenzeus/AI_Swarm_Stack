"""ops/restore.sh counts a Postgres load error as a failure (review OPS-R13: every load ended in `|| true`, an apply never
showed them and the drill passed with them). Its pg_errors() runs alone on psql's own error lines."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def errors(tmp_path, text):
    fn = re.search(r"^pg_errors\(\) \{.*\}$", (ROOT / "ops/restore.sh").read_text(), re.M).group(0)
    (tmp_path / "pg.err").write_text(text)
    return subprocess.run(["bash", "-c", f"W={tmp_path}\n{fn}\npg_errors"], capture_output=True, text=True).stdout.splitlines()


def test_a_load_error_counts_and_an_already_existing_role_does_not(tmp_path):
    assert errors(tmp_path, 'psql:<stdin>:12: ERROR:  role "litellm" already exists\n'
                            'psql:<stdin>:40: NOTICE:  table "x" does not exist, skipping\n') == []
    bad = errors(tmp_path, 'psql:<stdin>:12: ERROR:  role "litellm" already exists\n'
                           'psql:<stdin>:977: ERROR:  invalid input syntax for type json\n')
    assert bad == ["psql:<stdin>:977: ERROR:  invalid input syntax for type json"]
    assert errors(tmp_path, "") == []


def test_the_drill_and_the_apply_act_on_them():
    sh = (ROOT / "ops/restore.sh").read_text()
    assert 'if [ -n "$(pg_errors)" ]; then echo "postgres load errors' in sh and "RESTORE INCOMPLETE" in sh
    assert "0) echo \"    long-term memory restores nothing\"; bad=1" in sh
    assert re.search(r"^W=.*trap 'docker rm -f \"drill-pg-\$\$\" \"drill-hs-\$\$\"", sh, re.M)   # no drill container is left
