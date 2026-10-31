"""ops/missions.py: a parked run (park) hands the run slot to the next mission; the worker runs one model run at a time."""
import threading
import time


def test_a_parked_run_frees_the_slot(runner, monkeypatch):
    import missions as M
    monkeypatch.setattr(M.RTM, "emit", lambda *a, **k: None)
    order, gate = [], threading.Event()

    def slow_run():                                       # like the PC cleanup: holds the slot, then waits for Windows
        M._run_local.rid = 1
        M.slot.acquire()
        with M.lock:
            M.running.update(id=1, slug="pc", title="PC")
        order.append("pc starts")
        assert M.park("the Windows disk scan", gate.is_set, timeout=10, every=0.05)
        order.append("pc resumes")
        M.slot.release()

    t = threading.Thread(target=slow_run)
    t.start()
    for _ in range(100):                                  # the slot comes free while it is parked
        if M.slot.acquire(timeout=0.05):
            break
    with M.lock:
        assert M.parked[1]["waiting_for"] == "the Windows disk scan" and not M.running
    order.append("ram runs")                              # another mission does its model work meanwhile
    M.slot.release()
    gate.set()
    t.join(5)
    assert order == ["pc starts", "ram runs", "pc resumes"]
    assert not M.parked and M.running["slug"] == "pc"     # back in the slot, as it was
    M.running.clear()


def test_park_times_out(runner, monkeypatch):
    import missions as M
    monkeypatch.setattr(M.RTM, "emit", lambda *a, **k: None)
    t0 = time.time()
    assert M.park("nothing", lambda: False, timeout=0.2, every=0.05) is False
    assert time.time() - t0 < 2
