import threading

from run_trace import RunTrace


def test_step_numbers_unique_under_concurrency():
    t = RunTrace("robert", "q", "2026-11-12")

    def work():
        for _ in range(2000):
            t.add("worker:x", "a", None, None)
    threads = [threading.Thread(target=work) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    nums = [s["step"] for s in t.steps]
    assert len(nums) == 16000 and len(set(nums)) == 16000


def test_timing_has_router_ms():
    t = RunTrace("robert", "q", "2026-11-12")
    t.add("router", "route", None, {"intent": "analysis"}, duration_ms=12.4)
    assert t.timing()["router_ms"] == 12


def test_timing_reports_queued_ms():
    t = RunTrace("robert", "q", "2026-11-12")
    assert t.timing()["queued_ms"] == 0
    t.meta["queued_ms"] = 250
    assert t.timing()["queued_ms"] == 250
