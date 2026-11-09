"""ops/upgrade_check.py (review OPS-R10): every pinned component is checked, and one that cannot be checked is said."""
import upgrade_check as U


def test_every_pin_is_read_and_the_ones_it_missed_are_in():
    names = {n: pinned for n, pinned, _ in U.PINNED}
    for n in ("Home Assistant", "Claude Code", "Hindsight", "price watch", "Caddy (the gate)", "Forgejo runner", "LiteLLM"):
        assert n in names and not names[n].startswith("?"), (n, names.get(n))


def test_a_failed_lookup_is_a_row_and_part_of_the_message():
    def down():
        raise OSError("no network")
    rows, newer, unknown = U.check([("A", "1.0", lambda: "1.0"), ("B", "1.0", lambda: "1.2"), ("C", "1.0", down),
                                    ("D", "? (not in x)", lambda: "2.0")])
    assert newer[:1] == ["B 1.0 -> 1.2"] and unknown[:2] == ["C", "D"]
    assert any(r.startswith("? C") for r in rows) and any(r.startswith("? D") for r in rows)
    msg = U.message([], ["C"])
    assert msg and "could not check C" in msg              # nothing newer, yet the month's message is sent
    assert U.message([], []) is None
