"""Per-client session isolation.

Each MCP client session gets its own Runtime (hence its own session_state), so concurrent
agents never share or corrupt app state (origin R9). The Runtime is created lazily via an
injected factory, which keeps this testable without a real transport.
"""

from __future__ import annotations

from typing import Callable

from .runtime import Runtime


class SessionManager:
    def __init__(self, runtime_factory: Callable[[], Runtime]):
        self._factory = runtime_factory
        self._sessions: dict[str, Runtime] = {}

    def get_or_create(self, session_id: str) -> Runtime:
        rt = self._sessions.get(session_id)
        if rt is None:
            rt = self._factory()
            rt.run()
            self._sessions[session_id] = rt
        return rt

    def get(self, session_id: str) -> Runtime | None:
        return self._sessions.get(session_id)

    def dispose(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions

    @property
    def count(self) -> int:
        return len(self._sessions)
