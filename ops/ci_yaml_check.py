"""CI: every YAML file in the repo parses (encrypted secrets excluded). Compose's own tags (!reset, !override)
are valid there, so any tag is accepted; the structure is what is checked."""
import glob, sys

import yaml

yaml.SafeLoader.add_multi_constructor("!", lambda loader, suffix, node: None)
bad = []
for f in glob.glob("**/*.y*ml", recursive=True):
    if ".enc." in f:
        continue
    try:
        yaml.safe_load(open(f))
    except yaml.YAMLError as e:
        bad.append(f"{f}: {e}")
print("\n".join(bad) or "yaml ok")
sys.exit(1 if bad else 0)
