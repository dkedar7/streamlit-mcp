"""Session serialization (#178) and bounded session retention (#179)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from streamlit_mcp.session import SessionManager

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


class _Probe:
    """A stand-in runtime that records whether two calls were ever inside it at once."""

    created = 0

    def __init__(self):
        type(self).created += 1
        self.inside = 0
        self.overlapped = False

    def run(self):
        time.sleep(0.05)  # building a session runs the app; make first-touch races likely

    def work(self):
        self.inside += 1
        if self.inside > 1:
            self.overlapped = True
        time.sleep(0.01)
        self.inside -= 1


def _hammer(mgr, sids, calls=8):
    def call(sid):
        with mgr.use(sid) as rt:
            rt.work()
    threads = [threading.Thread(target=call, args=(sid,)) for sid in sids for _ in range(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_calls_on_one_session_never_overlap():
    _Probe.created = 0
    mgr = SessionManager(_Probe)
    _hammer(mgr, ["a"])
    assert not mgr.get("a").overlapped


def test_concurrent_first_touch_builds_one_runtime():
    """An unsynchronized check-then-set could build (and run the app for) two runtimes and keep
    whichever was written last."""
    _Probe.created = 0
    mgr = SessionManager(_Probe)
    _hammer(mgr, ["a"])
    assert _Probe.created == 1


def test_different_sessions_still_run_in_parallel():
    """Serialization is per session. One session's calls must not wait on another's."""
    gate = threading.Event()
    mgr = SessionManager(_Probe)
    mgr.get_or_create("a")
    mgr.get_or_create("b")

    def hold_a():
        with mgr.use("a"):
            gate.wait(5)

    t = threading.Thread(target=hold_a)
    t.start()
    try:
        done = threading.Event()

        def use_b():
            with mgr.use("b"):
                done.set()
        threading.Thread(target=use_b).start()
        assert done.wait(2), "session b blocked behind session a"
    finally:
        gate.set()
        t.join()


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_idle_sessions_expire_after_the_ttl():
    clock = _Clock()
    mgr = SessionManager(_Probe, ttl=60, clock=clock)
    mgr.get_or_create("old")
    clock.now = 30
    mgr.get_or_create("recent")
    clock.now = 70  # "old" idle 70s, "recent" 40s
    mgr.get_or_create("new")
    assert "old" not in mgr and "recent" in mgr and "new" in mgr


def test_max_sessions_evicts_the_least_recently_used():
    clock = _Clock()
    mgr = SessionManager(_Probe, max_sessions=2, clock=clock)
    mgr.get_or_create("a")
    clock.now = 1
    mgr.get_or_create("b")
    clock.now = 2
    mgr.get_or_create("a")      # a is now the most recent
    clock.now = 3
    mgr.get_or_create("c")
    assert mgr.count == 2 and "b" not in mgr and "a" in mgr and "c" in mgr


def test_a_session_with_a_call_in_flight_is_never_evicted():
    clock = _Clock()
    mgr = SessionManager(_Probe, ttl=1, max_sessions=1, clock=clock)
    with mgr.use("busy"):
        clock.now = 100
        mgr.get_or_create("other")  # would evict "busy" on both TTL and cap, if it were idle
        assert "busy" in mgr
    assert "other" in mgr


def test_no_eviction_by_default():
    clock = _Clock()
    mgr = SessionManager(_Probe, clock=clock)
    for i in range(20):
        clock.now = i * 10_000
        mgr.get_or_create(str(i))
    assert mgr.count == 20


def test_an_expired_session_starts_fresh():
    from streamlit_mcp.runtime import AppTestRuntime
    clock = _Clock()
    mgr = SessionManager(lambda: AppTestRuntime(APP), ttl=10, clock=clock)
    with mgr.use("s") as rt:
        rt.click("Save")
        assert rt.snapshot().session_state["saves"] == 1
    clock.now = 20
    mgr.get_or_create("t")  # any call triggers the sweep
    with mgr.use("s") as rt:
        assert rt.snapshot().session_state["saves"] == 0


# --- through the real server: concurrent tool calls on one session don't interleave ---
def test_concurrent_set_widget_calls_on_one_session_are_serialized():
    import asyncio

    from fastmcp import Client

    from streamlit_mcp.server import build_server

    async def main():
        async with Client(build_server(APP)) as client:
            results = await asyncio.gather(*[
                client.call_tool("click", {"identifier": "Save"}) for _ in range(10)
            ])
            state = (await client.call_tool("get_state", {})).data
            return results, state

    results, state = asyncio.run(main())
    assert all(not r.is_error for r in results)
    assert state["saves"] == 10  # every click landed exactly once


@pytest.mark.parametrize("argv,msg", [
    (["--session-ttl", "0"], "session-ttl"),
    (["--max-sessions", "0"], "max-sessions"),
])
def test_serve_rejects_nonsense_session_limits(argv, msg, capsys):
    from streamlit_mcp.cli import main
    assert main(["serve", APP, *argv]) == 1
    assert msg in capsys.readouterr().err
