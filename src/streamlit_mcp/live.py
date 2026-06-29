"""Live human-in-the-loop: opt in so an agent can edit your app while a browser watches.

Streamlit sessions are isolated, so an agent driving your app over MCP doesn't update a live
browser by itself — that needs **shared state the app re-reads**. ``live(...)`` bridges them:
the agent's ``set_widget``/``click`` (over streamlit-mcp) rerun the app, which persists its
widget state to a small versioned store; a ``st.fragment(run_every=...)`` polls the version and
reruns the browser to adopt the change. Purely app-side — no new MCP tools, no browser automation.

    import streamlit as st
    from streamlit_mcp.live import live

    with live("signup", defaults={"name": "Ada", "plan": "Free"}):
        st.text_input("Name", key="name")
        st.selectbox("Plan", ["Free", "Pro", "Team"], key="plan")

``defaults`` declares the synced ``session_state`` keys and their initial values; the synced
widgets must use matching ``key=``\\ s. Run ``streamlit run app.py`` (the human) and
``streamlit-mcp serve app.py`` (the agent) on the same file — the browser updates within
``run_every`` of the agent's edit.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import streamlit as st

# Internal session_state key holding the store version this session has adopted.
_VKEY = "_smcp_live_v"


def _encode(o: Any) -> dict:
    """JSON ``default`` for values Streamlit widgets produce that JSON can't (date/datetime/time).
    Encoded to a tagged form so :func:`_decode` can restore the real object on the way back."""
    if isinstance(o, _dt.datetime):  # check before date (datetime subclasses date)
        return {"__dt__": o.isoformat()}
    if isinstance(o, _dt.date):
        return {"__date__": o.isoformat()}
    if isinstance(o, _dt.time):
        return {"__time__": o.isoformat()}
    raise TypeError(
        f"live() can't sync a value of type {type(o).__name__!r} through the default FileStore "
        "(JSON values plus date/datetime/time only). Use a JSON-native value or pass a custom store=."
    )


def _decode(d: dict) -> Any:
    """``object_hook`` mirror of :func:`_encode`: restore tagged date/datetime/time values."""
    if "__date__" in d:
        return _dt.date.fromisoformat(d["__date__"])
    if "__dt__" in d:
        return _dt.datetime.fromisoformat(d["__dt__"])
    if "__time__" in d:
        return _dt.time.fromisoformat(d["__time__"])
    return d


@runtime_checkable
class Store(Protocol):
    """A versioned key/value backend. Implement this to use a custom store (e.g. Redis)."""

    def load(self) -> tuple[int, dict]:
        """Return ``(version, fields)``; ``(0, {})`` when nothing has been stored yet."""
        ...

    def save(self, fields: dict, version: int) -> None:
        """Persist ``fields`` at ``version`` (must be durable to other processes)."""
        ...


class FileStore:
    """Default store: one JSON file, written atomically so readers never see a torn write.

    The shape on disk is ``{"v": <int>, "fields": {...}}``. Fine for a single machine; pass a
    custom :class:`Store` for multiple servers.
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def load(self) -> tuple[int, dict]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"), object_hook=_decode)
            return int(d.get("v", 0)), dict(d.get("fields", {}))
        except (OSError, ValueError):
            return 0, {}

    def save(self, fields: dict, version: int) -> None:
        payload = json.dumps({"v": int(version), "fields": fields}, default=_encode)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)  # atomic on the same filesystem


def _default_store(name: str) -> FileStore:
    """A FileStore both ``streamlit run`` and ``streamlit-mcp serve`` resolve to from ``name``."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name) or "app"
    return FileStore(Path(tempfile.gettempdir()) / f"streamlit_mcp_live_{safe}.json")


class LiveSync:
    """Context manager returned by :func:`live`. Re-seeds widget state from the store on enter
    (before any widget is created — the only point Streamlit lets you overwrite a widget's
    ``session_state``), and on exit persists local edits and installs the polling fragment."""

    def __init__(self, name: str, *, defaults: dict[str, Any],
                 store: Optional[Store] = None, run_every: str = "1s"):
        self.name = name
        self.defaults = dict(defaults)
        self.store: Store = store or _default_store(name)
        self.run_every = run_every
        self._v = 0
        self._fields: dict = {}

    def __enter__(self) -> "LiveSync":
        v, fields = self.store.load()
        merged = {**self.defaults, **{k: fields[k] for k in self.defaults if k in fields}}
        if st.session_state.get(_VKEY) != v:  # adopt an external change, before widgets exist
            for k in self.defaults:
                st.session_state[k] = merged[k]
            st.session_state[_VKEY] = v
        self._v, self._fields = v, merged
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            cur = {k: st.session_state.get(k, self._fields[k]) for k in self.defaults}
            if cur != self._fields:  # a widget the human (or the agent's rerun) changed
                self._v += 1
                self.store.save(cur, self._v)
                st.session_state[_VKEY] = self._v
            self._install_poll()
        return False  # never suppress exceptions

    def _install_poll(self) -> None:
        # The poll (a run_every fragment) only matters in a real browser session. Skip it under
        # AppTest — the agent driving over MCP, or tests — where there's no browser to refresh and
        # a run_every fragment can hang the headless run. AppTest mocks the runtime, so a genuine
        # Runtime instance is the reliable signal: st.runtime.exists() is True under BOTH.
        try:
            import streamlit.runtime as _rt
            from streamlit.runtime import Runtime
            if not (_rt.exists() and isinstance(_rt.get_instance(), Runtime)):
                return
        except Exception:
            return
        store, run_every = self.store, self.run_every

        @st.fragment(run_every=run_every)
        def _poll() -> None:
            v, _ = store.load()
            if v != st.session_state.get(_VKEY):
                st.rerun(scope="app")  # adopt the agent's (or another browser's) edit

        _poll()


def live(name: str, *, defaults: dict[str, Any], store: Optional[Store] = None,
         run_every: str = "1s") -> LiveSync:
    """Sync an app's widget state through a shared store so an agent's MCP edits show up live.

    Args:
        name: identifies the shared store; ``streamlit run`` and ``streamlit-mcp serve`` must
            use the same ``name`` (the default :class:`FileStore` path is derived from it).
        defaults: the synced ``session_state`` keys and their initial values. Synced widgets
            must use matching ``key=``\\ s; action buttons are represented as a flag set by the
            app (e.g. ``created``).
        store: a custom :class:`Store` (e.g. Redis) for multi-node; defaults to a local file.
        run_every: how often the browser polls the store for external edits.

    Returns:
        a :class:`LiveSync` context manager — use it as ``with live(...): ...`` around your widgets.
    """
    return LiveSync(name, defaults=defaults, store=store, run_every=run_every)
