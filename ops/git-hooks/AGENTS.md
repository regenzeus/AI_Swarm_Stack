# ops/git-hooks/: the stack repository's git hooks

`core.hooksPath` points here (ops/termguard.py install, run by every deploy). Each hook only calls ops/termguard.py: a
commit or push that holds what the deployment's private never-in-git list forbids is refused (SEC-22). The list itself
is never in a repository. Do not add hooks that do anything else.
