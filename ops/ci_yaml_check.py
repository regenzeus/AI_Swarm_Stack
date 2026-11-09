"""CI: every YAML file in the repo parses (encrypted secrets excluded). Compose's own tags (!reset, !override)
are valid there, so any tag is accepted; the structure is what is checked."""
import glob, sys

import yaml

yaml.SafeLoader.add_multi_constructor("!", lambda loader, suffix, node: None)
bad, n = [], 0
# include_hidden: .forgejo/workflows/ci.yml and .semgrep.yml were never parsed (review QA-R10)
for f in glob.glob("**/*.y*ml", recursive=True, include_hidden=True):
    if ".enc." in f or f.startswith(".git/"):
        continue
    n += 1
    try:
        yaml.safe_load(open(f))
    except yaml.YAMLError as e:
        bad.append(f"{f}: {e}")
print("\n".join(bad) or f"yaml ok ({n} files)" if n else "no YAML file found: nothing was checked")
sys.exit(1 if bad or not n else 0)
