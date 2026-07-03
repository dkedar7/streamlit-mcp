"""streamlit-mcp — serve a Streamlit app as an MCP server, no browser.

The app is driven headlessly through Streamlit's AppTest runtime (behind a Runtime
interface); widgets auto-map to MCP tools, and a human-first CLI exercises the same
engine an agent uses (parity).
"""

__version__ = "0.3.5"

# Public API
# Live human-in-the-loop sync lives in the `streamlit_mcp.live` submodule (import it directly:
# `from streamlit_mcp.live import live`). It is not re-exported here so `import streamlit_mcp`
# stays cheap — `live` imports streamlit eagerly, whereas the core path defers it.
from .decorator import mcp_tool  # noqa: E402
from .engine import Engine, PermissionDenied  # noqa: E402
from .guardrails import Guardrails  # noqa: E402
from .runtime import AppTestRuntime, Runtime, RuntimeError_, WidgetNotFound  # noqa: E402
from .server import build_server, serve  # noqa: E402

__all__ = [
    "__version__",
    "mcp_tool",
    "Engine",
    "PermissionDenied",
    "Guardrails",
    "AppTestRuntime",
    "Runtime",
    "RuntimeError_",
    "WidgetNotFound",
    "build_server",
    "serve",
]
