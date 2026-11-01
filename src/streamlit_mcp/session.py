"""Per-client session isolation.

Each MCP client session gets its own Runtime (hence its own session_state), so concurrent
agents never share or corrupt app state (origin R9). The Runtime is created lazily via an
injected factory, which keeps this testable without a real transport.

Two lifecycle guarantees sit on top of the isolation:

* **One in-flight call per session (#178).** FastMCP runs sync tools in a threadpool, so two
  requests on one HTTP/SSE session reached the same non-re-entrant AppTest from two threads and
  interleaved its reruns: silent session_state corruption reported as two successes. ``use()``
  holds the session's own lock for the whole operation, so a second call on that session waits.
  Different sessions keep their own locks and stay fully parallel.
* **Bounded memory (#179).** Every session id used to mint a runtime that lived for the life of the
  process. Opt-in ``ttl`` (idle seconds) and ``max_sessions`` (LRU cap) evict old ones. Both
  default to off, so stdio and existing deployments behave exactly as before.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Callable, Iterator, Optional

from .runtime import Runtime


class _Session:
    __slots__ = ("lock", "runtime", "last_used", "busy")

    def __init__(self) -> None:
        self.lock = threading.Lock()   # serializes every operation on this session's runtime
        self.runtime: Optional[Runtime] = None
        self.last_used = time.monotonic()
        self.busy = 0                  # calls holding or waiting on `lock`; never evicted while > 0


class SessionManager:
    def __init__(self, runtime_factory: Callable[[], Runtime], *, ttl: Optional[float] = None,
                 max_sessions: Optional[int] = None, clock: Callable[[], float] = time.monotonic):
        self._factory = runtime_factory
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()  # guards the map itself, never held across an app run
        self._ttl = ttl or None
        self._max = max_sessions or None
        self._clock = clock

    @contextlib.contextmanager
    def use(self, session_id: str) -> Iterator[Runtime]:
        """The session's runtime, held exclusively for the duration of the ``with`` block."""
        with self._lock:
            self._evict_locked(keep=session_id)
            entry = self._sessions.get(session_id)
            if entry is None:
                entry = self._sessions[session_id] = _Session()
            entry.busy += 1
        try:
            with entry.lock:
                # Created under the SESSION lock, not the map lock: building a runtime runs the app,
                # and doing that under the map lock would stall every other session's first call.
                # Two first-touch calls for one id both land here, and only the first builds it.
                if entry.runtime is None:
                    rt = self._factory()
                    rt.run()
                    entry.runtime = rt
                yield entry.runtime
        finally:
            with self._lock:
                entry.busy -= 1
                entry.last_used = self._clock()

    def get_or_create(self, session_id: str) -> Runtime:
        """The session's runtime, without holding it. Callers that drive the runtime should use
        ``use()``, so that concurrent calls on one session are serialized."""
        with self.use(session_id) as rt:
            return rt

    def get(self, session_id: str) -> Runtime | None:
        entry = self._sessions.get(session_id)
        return entry.runtime if entry is not None else None

    def dispose(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def _evict_locked(self, keep: str) -> None:
        """Drop idle-expired sessions, then the least-recently-used beyond the cap. A session with
        a call in flight is never evicted, and neither is the one being asked for."""
        def idle(item):
            sid, entry = item
            return sid != keep and entry.busy == 0
        if self._ttl is not None:
            cutoff = self._clock() - self._ttl
            for sid, entry in list(self._sessions.items()):
                if idle((sid, entry)) and entry.last_used < cutoff:
                    del self._sessions[sid]
        if self._max is not None:
            # Room for `keep` if it's about to be created.
            limit = self._max - (0 if keep in self._sessions else 1)
            candidates = sorted(filter(idle, self._sessions.items()), key=lambda i: i[1].last_used)
            while len(self._sessions) > limit and candidates:
                del self._sessions[candidates.pop(0)[0]]

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions

    @property
    def count(self) -> int:
        return len(self._sessions)
